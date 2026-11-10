import copy
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.scheduling import preview
from backend.app.scheduling.solver import ScheduleVerificationError
from backend.tests.test_scheduling_loader import provider, sql_payload

WEEK = {"week_start": "2026-11-09"}
BASE = "http://127.0.0.1:8000"


def client_for(settings, **kwargs):
    return TestClient(create_app(settings), base_url=BASE, client=("127.0.0.1", 51000), **kwargs)


def test_real_http_snapshot_to_solver_preview_is_complete_private_and_read_only(provider):
    settings, state = provider
    before = copy.deepcopy(state["payload"])
    with client_for(settings) as client:
        response = client.post("/api/schedules/generate", json=WEEK)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["has_solution"] and data["status"] in ("OPTIMAL", "FEASIBLE")
        assert data["scope"] == "week"
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
    assert len(state["calls"]) == 1  # Only read-only load RPC; no booking API.
    assert state["calls"][0]["path"] == "/rest/v1/rpc/load_scheduling_data"
    assert state["calls"][0]["parameters"]["p_week_start"] == WEEK["week_start"]


@pytest.mark.parametrize("body", [
    {}, {"week_start": "2026-11-10"}, {"week_start": "2026-02-30"},
    {"week_start": "2026-11-09T00:00:00Z"}, {"week_start": 1794182400},
    {"week_start": None}, {"week_start": "9999-12-27"},
    {**WEEK, "student_ids": []}, {**WEEK, "max_time_seconds": 5000},
])
def test_invalid_request_does_not_load_database(provider, body):
    settings, state = provider
    with client_for(settings) as client:
        assert client.post("/api/schedules/generate", json=body).status_code == 422
    assert not state["calls"]


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
        assert response.json()["detail"]["code"] == "DATABASE_UNAVAILABLE"
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
            assert len(state["calls"]) == 1
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
    with TestClient(create_app(settings), base_url=BASE, client=peer, headers=headers) as client:
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
    assert len(state["calls"]) == 1


@pytest.mark.parametrize("host", ["localhost", "[::1]"])
def test_loopback_hostname_and_ipv6_access(provider, host):
    settings, _ = provider
    with TestClient(create_app(settings), base_url=f"http://{host}:8000", client=("::1", 51000)) as client:
        assert client.get(preview.PAGE_PATH).status_code == 200
