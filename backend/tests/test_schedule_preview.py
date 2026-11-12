import copy
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi.testclient import TestClient

from backend.app.auth import SessionUser, get_session
from backend.app.main import create_app
from backend.app.scheduling import preview
from backend.app.scheduling.solver import ScheduleVerificationError
from backend.tests.test_scheduling_loader import provider, sql_payload, uid

ADMIN = SessionUser(role="admin", name="Test Admin", profile_id="00000000-0000-0000-0000-0000000000ad", home="/admin")
WEEK = {"week_start": "2026-11-09", "intake_id": uid(1)}
BASE = "http://127.0.0.1:8000"


@pytest.fixture
def traces():
    from backend.app.observability import LOGGER
    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record.trace_fields)

    handler = Capture()
    LOGGER.addHandler(handler)
    try:
        yield records
    finally:
        LOGGER.removeHandler(handler)


def as_admin(app):
    """Act as a logged-in administrator (login itself is covered by test_auth.py)."""
    app.dependency_overrides[get_session] = lambda: ADMIN
    return app


def client_for(settings, **kwargs):
    return TestClient(as_admin(create_app(settings)), base_url=BASE, client=("127.0.0.1", 51000), **kwargs)


def test_real_http_snapshot_to_solver_preview_is_complete_private_and_read_only(provider):
    settings, state = provider
    before = copy.deepcopy(state["payload"])
    with client_for(settings) as client:
        response = client.post("/api/schedules/generate", json=WEEK)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["has_solution"] and data["status"] in ("OPTIMAL", "FEASIBLE")
        assert data["scope"] == "intake"
        assert data["intake_id"] == uid(1) and data["group_number"] is None
        assert len(data["placements"]) == data["required_count"] == 1
        assert data["quality_optimized"] is False and data["quality"] is None
        assert len(data["snapshot_revision"]) == 64
        placement = data["placements"][0]
        lesson = next(item for item in before["requirements"] if item["needs_scheduling"])
        assert placement["occurrence_id"] == lesson["occurrence_id"]
        assert placement["course_code"] == lesson["course_code"]
        assert placement["group_number"] == lesson["group_number"]
        assert placement["room_name"]
        assert response.headers["cache-control"] == "no-store"
        assert data["statistics"]["max_time_seconds"] == settings.scheduling.solver.max_time_seconds
        for private in ("student_ids", "sb_secret_snapshot_test", "database_snapshot", "captured_at"):
            assert private not in response.text
        private_roster_ids = {value for roster in before["rosters"] for value in roster["student_ids"]}
        assert all(value not in response.text for value in private_roster_ids)
    assert state["payload"] == before
    assert len(state["calls"]) > 1
    assert all(call["path"].startswith("/rest/v1/") and "/rpc/" not in call["path"] for call in state["calls"])
    assert all(call["path"] in {
        "/rest/v1/teaching_occurrence_details", "/rest/v1/class_session_details", "/rest/v1/class_sessions",
        "/rest/v1/meeting_sessions", "/rest/v1/meeting_students", "/rest/v1/student_intakes",
        "/rest/v1/rooms", "/rest/v1/lecturers",
    } for call in state["calls"])


@pytest.mark.parametrize("body", [
    {}, {"week_start": "2026-11-10"}, {"week_start": "2026-02-30"},
    {"week_start": "2026-11-09T00:00:00Z"}, {"week_start": 1794182400},
    {"week_start": None}, {"week_start": "9999-12-27"},
    {**WEEK, "student_ids": []}, {**WEEK, "max_time_seconds": 5000},
    {**WEEK, "intake_id": "not-a-uuid"}, {**WEEK, "group_number": 0},
    {**WEEK, "group_number": -1}, {**WEEK, "group_number": 1.5},
    {**WEEK, "group_number": True}, {**WEEK, "group_number": "1"},
])
def test_invalid_request_does_not_load_database(provider, body):
    settings, state = provider
    body = {"intake_id": uid(1), **body} if body else body
    with client_for(settings) as client:
        assert client.post("/api/schedules/generate", json=body).status_code == 422
    assert not state["calls"]


def test_intake_is_required_and_group_filter_does_not_expand_scope(provider):
    settings, state = provider
    with client_for(settings) as client:
        assert client.post("/api/schedules/generate", json={"week_start": WEEK["week_start"]}).status_code == 422
        assert not state["calls"]
        for selection in ({**WEEK, "group_number": 2}, {**WEEK, "intake_id": uid(2)}):
            response = client.post("/api/schedules/generate", json=selection)
            assert response.status_code == 200
            assert response.json()["status"] == "NO_PENDING_REQUIREMENTS"
            assert response.json()["placements"] == []


def test_selected_group_excludes_other_pending_demand_but_all_intake_groups_are_joint(provider):
    settings, state = provider
    source = next(row for row in state["payload"]["requirements"] if row["needs_scheduling"])
    # Group 2 of this intake and another intake have impossible pending demand.
    # Selecting group 1 must not attempt to place either unrelated occurrence.
    for number, intake_id, group in [(600, uid(1), 2), (700, uid(3), 1)]:
        lesson = {**source, "occurrence_id": uid(number), "section_id": uid(number + 1),
                  "plan_id": uid(number + 2), "intake_id": intake_id, "group_number": group, "duration_minutes": 6000}
        state["payload"]["requirements"].append(lesson)
        state["payload"]["rosters"].append({"section_id": lesson["section_id"], "intake_id": intake_id,
                                             "group_number": group, "student_ids": [uid(10)]})
    with client_for(settings) as client:
        selected = client.post("/api/schedules/generate", json={**WEEK, "group_number": 1}).json()
        assert selected["has_solution"] and selected["required_count"] == 1
        assert selected["scope"] == "intake_group" and selected["group_number"] == 1
        assert all(p["intake_id"] == uid(1) and p["group_number"] == 1 for p in selected["placements"])
        all_groups = client.post("/api/schedules/generate", json=WEEK).json()
        assert all_groups["status"] == "INFEASIBLE" and all_groups["required_count"] == 2
        other = client.post("/api/schedules/generate", json={**WEEK, "intake_id": uid(3)}).json()
        assert other["status"] == "INFEASIBLE" and other["required_count"] == 1
        assert len({selected["snapshot_revision"], all_groups["snapshot_revision"], other["snapshot_revision"]}) == 3


def test_scoped_projection_keeps_cross_intake_students_and_all_fixed_bookings(provider):
    from datetime import datetime
    from backend.tests.test_scheduling_loader import read
    from backend.app.scheduling.candidates import generate_candidates
    from backend.app.scheduling.validator import BookingProposal, validate_booking
    from uuid import UUID

    snapshot = read(provider)
    selected = preview.select_scope(snapshot, UUID(uid(1)), 1)
    assert selected.class_bookings is snapshot.class_bookings
    assert selected.meeting_bookings is snapshot.meeting_bookings
    assert selected.rooms is snapshot.rooms
    assert selected.pending_requirements[0].student_ids == snapshot.pending_requirements[0].student_ids
    assert all(item.intake_id == UUID(uid(1)) for item in selected.requirements)
    assert any(item.intake_id != UUID(uid(1)) for item in selected.class_bookings)
    lesson = selected.pending_requirements[0]
    # Different lecturer and room, but a student attends both intakes.
    blocked = datetime.fromisoformat("2026-11-09T14:43:00+08:00")
    proposal = BookingProposal(occurrence_id=lesson.occurrence_id, room_id=UUID(uid(60)), starts_at=blocked)
    assert "STUDENT_CONFLICT" in validate_booking(selected, proposal).reason_codes
    assert not any(item.contains(blocked) for item in generate_candidates(selected, lesson.occurrence_id).ranges)
    assert preview.select_scope(snapshot, UUID(uid(1)), 1).revision == selected.revision
    assert preview.select_scope(snapshot, UUID(uid(1)), 2).revision != selected.revision


def test_empty_week_and_infeasibility_are_explicit_non_partial_results(provider):
    settings, state = provider
    original = copy.deepcopy(state["payload"])
    with client_for(settings) as client:
        state["payload"]["requirements"] = [item for item in original["requirements"] if not item["needs_scheduling"]]
        empty = client.post("/api/schedules/generate", json=WEEK)
        assert empty.status_code == 200
        assert empty.json()["status"] == "NO_PENDING_REQUIREMENTS"
        assert not empty.json()["has_solution"] and not empty.json()["placements"]
        state["payload"] = original
        for room in state["payload"]["rooms"]:
            room["is_active"] = False
        impossible = client.post("/api/schedules/generate", json=WEEK)
        assert impossible.status_code == 200
        data = impossible.json()
        assert data["status"] == "INFEASIBLE" and not data["placements"]
        assert data["candidate_failures"] and not data["has_solution"]


def test_tiny_search_budget_returns_unknown_without_claiming_infeasible(provider):
    settings, _ = provider
    settings.scheduling.solver.max_time_seconds = 1e-9
    with client_for(settings) as client:
        response = client.post("/api/schedules/generate", json=WEEK)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "UNKNOWN" and not data["placements"]
        assert data["diagnostics"][0]["code"] == "SEARCH_INCOMPLETE"


@pytest.mark.parametrize("status,body", [(401, b'{"secret":"provider-error"}'), (404, b'{}'), (500, b'<html>provider-error</html>'), (200, b'not json')])
def test_provider_failure_is_safe_and_capacity_is_released(provider, status, body):
    settings, state = provider
    state.update(status=status, body=body)
    with client_for(settings) as client:
        response = client.post("/api/schedules/generate", json=WEEK)
        assert response.status_code == 502
        assert response.json()["detail"]["code"] == ("DATABASE_PERMISSION_DENIED" if status in (401, 403) else "DATABASE_UNAVAILABLE")
        assert "provider-error" not in response.text
        state.update(status=200, body=None)
        assert client.post("/api/schedules/generate", json=WEEK).status_code == 200


def test_timeout_missing_config_and_malformed_scheduling_data(provider, monkeypatch):
    settings, state = provider
    settings.supabase.timeout_seconds = 0.05
    state["delay"] = 0.2
    with client_for(settings) as client:
        response = client.post("/api/schedules/generate", json=WEEK)
        assert response.status_code == 504
        assert response.json()["detail"]["code"] == "DATABASE_TIMEOUT"
        state.update(delay=0, payload={})
        response = client.post("/api/schedules/generate", json=WEEK)
        assert response.status_code == 502
        assert response.json()["detail"]["code"] == "INVALID_SNAPSHOT"
        monkeypatch.delenv(settings.supabase.key_env)
        response = client.post("/api/schedules/generate", json=WEEK)
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "DATABASE_NOT_CONFIGURED"


@pytest.mark.parametrize("kind", ["verification", "invalid_model", "unexpected"])
def test_internal_failures_never_return_assignments_or_exception_text(provider, monkeypatch, kind):
    settings, _ = provider
    real_solve = preview.solve_weekly_schedule

    def broken(*args):
        if kind == "invalid_model":
            return real_solve(*args).model_copy(update={"status": "MODEL_INVALID", "placements": ()})
        if kind == "verification":
            raise ScheduleVerificationError("private student payload")
        raise RuntimeError("private student payload")

    monkeypatch.setattr(preview, "solve_weekly_schedule", broken)
    with client_for(settings) as client:
        response = client.post("/api/schedules/generate", json=WEEK)
        assert response.status_code == 500
        assert "placements" not in response.text and "private student payload" not in response.text
        assert response.json()["detail"]["code"] == ("MODEL_INVALID" if kind == "invalid_model" else "GENERATION_FAILED")
        monkeypatch.setattr(preview, "solve_weekly_schedule", real_solve)
        assert client.post("/api/schedules/generate", json=WEEK).status_code == 200


def test_one_generation_at_a_time_and_health_responds_during_solve(provider, monkeypatch):
    settings, state = provider
    started, release = Event(), Event()
    real_solve = preview.solve_weekly_schedule

    def waiting_solver(*args):
        started.set()
        assert release.wait(5)
        return real_solve(*args)

    monkeypatch.setattr(preview, "solve_weekly_schedule", waiting_solver)
    with client_for(settings) as client, ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(client.post, "/api/schedules/generate", json=WEEK)
        try:
            assert started.wait(5)
            assert client.get("/api/health").status_code == 200
            busy = client.post("/api/schedules/generate", json=WEEK)
            assert busy.status_code == 429
            assert busy.json()["detail"]["code"] == "GENERATION_BUSY"
            assert busy.headers["retry-after"] == "2"
            assert len(state["calls"]) > 1
        finally:
            release.set()
        assert future.result(timeout=5).status_code == 200
        assert client.post("/api/schedules/generate", json=WEEK).status_code == 200


@pytest.mark.parametrize("case", ["production", "remote", "host", "origin", "forwarded"])
def test_access_rejected_before_database_for_page_assets_and_api(provider, case):
    settings, state = provider
    peer, headers = ("127.0.0.1", 51000), {}
    if case == "production":
        settings.app.environment = "production"
    elif case == "remote":
        peer = ("192.0.2.10", 51000)
    elif case == "host":
        headers = {"Host": "attacker.example"}
    elif case == "origin":
        headers = {"Origin": "https://attacker.example"}
    else:
        headers = {"X-Forwarded-For": "127.0.0.1"}
    with TestClient(as_admin(create_app(settings)), base_url=BASE, client=peer, headers=headers) as client:
        expected = 404 if case == "production" else 403
        assert client.post("/api/schedules/generate", json=WEEK).status_code == expected
        for path in (preview.PAGE_PATH, preview.PAGE_PATH + "/app.js", preview.PAGE_PATH + "/style.css"):
            assert client.get(path).status_code == expected
    assert not state["calls"]


def test_page_assets_openapi_and_cors_are_available_without_frontend_build(provider):
    settings, state = provider
    with client_for(settings) as client:
        page = client.get(preview.PAGE_PATH)
        assert page.status_code == 200
        assert "Scheduling preview" in page.text and 'data-timezone="Asia/Kuala_Lumpur"' in page.text
        assert page.headers["cache-control"] == "no-store"
        assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
        for asset, mime in (("app.js", "text/javascript"), ("style.css", "text/css")):
            result = client.get(f"{preview.PAGE_PATH}/{asset}")
            assert result.status_code == 200 and mime in result.headers["content-type"]
        schema = client.get("/openapi.json").json()
        assert "post" in schema["paths"]["/api/schedules/generate"]
        assert "SchedulePreview" in schema["components"]["schemas"]
        options = client.options("/api/schedules/generate", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"})
        assert options.status_code == 200 and "POST" in options.headers["access-control-allow-methods"]
        response = client.post("/api/schedules/generate", json=WEEK, headers={"Origin": "http://localhost:5173"})
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert len(state["calls"]) > 1


@pytest.mark.parametrize("host", ["localhost", "[::1]"])
def test_loopback_hostname_and_ipv6_access(provider, host):
    settings, _ = provider
    with TestClient(as_admin(create_app(settings)), base_url=f"http://{host}:8000", client=("::1", 51000)) as client:
        assert client.get(preview.PAGE_PATH).status_code == 200


@pytest.mark.parametrize("provider_status", [404, 401, 500])
def test_table_read_error_is_traced_without_private_bodies(provider, traces, provider_status):
    settings, state = provider
    state.update(status=provider_status, body=json.dumps({"code": "PRIVATE-CODE", "message": "PRIVATE-STUDENT-PAYLOAD",
                                             "details": "sb_secret_DO_NOT_LOG", "hint": "PRIVATE-STUDENT-PAYLOAD"}).encode())
    with client_for(settings) as client:
        response = client.post("/api/schedules/generate", json=WEEK, headers={"X-Request-ID": "injected-caller-value"})
        assert response.status_code == 502
        detail = response.json()["detail"]
        assert detail["code"] == "DATABASE_UNAVAILABLE"
        trace_id = response.headers["x-request-id"]
        assert re.fullmatch("[0-9a-f]{32}", trace_id)
        assert detail["request_id"] == trace_id
        records = [item for item in traces if item["request_id"] == trace_id]
        failed = next(item for item in records if item["event"] == "snapshot_query_failed")
        assert failed["stage"] == "load_requirements"
        assert failed["provider_status"] == provider_status
        assert failed["exception_type"] == "SupabaseReadError"
        assert records[-1]["event"] == "request_completed" and records[-1]["http_status"] == 502
        assert not any(item["event"] == "solver_started" for item in records)
        output = response.text + json.dumps(records)
        assert all(secret not in output for secret in ("PRIVATE-STUDENT-PAYLOAD", "sb_secret_DO_NOT_LOG", "injected-caller-value", "UNTRUSTED-SECRET"))


def test_success_and_validation_errors_have_separate_request_ids(provider, traces):
    settings, state = provider
    with client_for(settings) as client:
        success = client.post("/api/schedules/generate", json=WEEK)
        invalid = client.post("/api/schedules/generate", json={})
        denied = client.post("/api/schedules/generate", json=WEEK, headers={"Origin": "https://unapproved.example"})
        assert (success.status_code, invalid.status_code, denied.status_code) == (200, 422, 403)
        identifiers = [item.headers["x-request-id"] for item in (success, invalid, denied)]
        assert len(set(identifiers)) == 3
        selected = [item for item in traces if item["request_id"] == identifiers[0]]
        assert {item["event"] for item in selected} >= {"request_started", "snapshot_query_started", "snapshot_query_completed", "snapshot_loaded", "solver_started", "solver_completed", "request_completed"}
        assert next(item for item in selected if item["event"] == "solver_completed")["placement_count"] == 1
        assert "X-Request-ID" in client.post("/api/schedules/generate", json={}, headers={"Origin": "http://localhost:5173"}).headers["access-control-expose-headers"]
    assert len(state["calls"]) > 1
    output = json.dumps(traces)
    assert "student_ids" not in output and "intake_id" not in output and "sb_secret_snapshot_test" not in output


def test_internal_failure_logs_stack_locations_without_messages_or_locals(provider, traces, monkeypatch):
    settings, _ = provider

    def failing_solver(*args):
        private_student_record = "PRIVATE-STUDENT-RECORD"
        raise RuntimeError(private_student_record)

    monkeypatch.setattr(preview, "solve_weekly_schedule", failing_solver)
    with client_for(settings) as client:
        response = client.post("/api/schedules/generate", json=WEEK)
        assert response.status_code == 500
    failure = next(item for item in traces if item["event"] == "generation_failed")
    assert failure["request_id"] == response.headers["x-request-id"]
    assert failure["exception_type"] == "RuntimeError"
    assert failure["frames"] and failure["frames"][-1]["function"] == "failing_solver"
    assert all("/" not in frame["file"] and "\\" not in frame["file"] for frame in failure["frames"])
    assert "PRIVATE-STUDENT-RECORD" not in response.text + json.dumps(traces)
