"""Step 10: saving a reviewed preview. Uses the same real-PostgreSQL-output HTTP
stand-in as the preview tests, extended with a class_sessions bulk insert."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.scheduling import preview
from backend.tests.test_schedule_preview import ADMIN, BASE, WEEK, as_admin, client_for, traces  # noqa: F401 (fixture)
from backend.tests.test_scheduling_loader import provider, sql_payload, uid  # noqa: F401 (fixtures)

SAVE = "/api/schedules/save"


def generate(client, body=WEEK):
    response = client.post("/api/schedules/generate", json=body)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["has_solution"], data
    return data


def save_body(data, **changes):
    body = {
        "week_start": data["week_start"], "intake_id": data["intake_id"], "group_number": data["group_number"],
        "snapshot_revision": data["snapshot_revision"],
        "placements": [{key: item[key] for key in ("occurrence_id", "room_id", "starts_at")} for item in data["placements"]],
    }
    return {**body, **changes}


def detail(response):
    return response.json()["detail"]


def test_save_writes_whole_preview_in_one_insert_and_retry_is_rejected(provider):
    settings, state = provider
    with client_for(settings) as client:
        data = generate(client)
        response = client.post(SAVE, json=save_body(data))
        assert response.status_code == 201, response.text
        saved = response.json()
        assert saved["status"] == "SAVED" and saved["saved_count"] == 1 == len(data["placements"])
        assert saved["scope"] == "intake" and saved["intake_id"] == uid(1) and saved["group_number"] is None
        assert saved["saved"][0]["occurrence_id"] == data["placements"][0]["occurrence_id"]
        assert response.headers["cache-control"] == "no-store"
        assert len(state["writes"]) == 1
        write = state["writes"][0]
        assert write["path"] == "/rest/v1/class_sessions"
        assert write["headers"]["Prefer"] == "return=representation"
        assert write["parameters"]["select"] == "id,occurrence_id"
        row = write["rows"][0]
        placement = data["placements"][0]
        # Only booking columns are written; section comes from the database, not the client.
        assert set(row) == {"occurrence_id", "section_id", "room_id", "starts_at", "status", "created_by"}
        assert row["status"] == "scheduled" and row["section_id"] == placement["section_id"]
        # Save audit: every row names the saving admin's Supabase user; the database trigger
        # turns it into a schedule_changes 'create' row in the same statement.
        assert all(item["created_by"] == ADMIN.auth_user_id for item in write["rows"])
        assert saved["saved_by"] == ADMIN.name and ADMIN.auth_user_id not in response.text
        assert row["room_id"] == placement["room_id"]

        # The saved class is now a fixed booking: nothing left to schedule.
        again = client.post("/api/schedules/generate", json=WEEK).json()
        assert again["status"] == "NO_PENDING_REQUIREMENTS"
        # A retried save of the same preview is stale, and writes nothing.
        retry = client.post(SAVE, json=save_body(data))
        assert retry.status_code == 409 and detail(retry)["code"] == "PREVIEW_STALE"
        assert len(state["writes"]) == 1


def test_selected_group_save_keeps_scope(provider):
    settings, state = provider
    with client_for(settings) as client:
        data = generate(client, {**WEEK, "group_number": 1})
        response = client.post(SAVE, json=save_body(data))
        assert response.status_code == 201
        assert response.json()["scope"] == "intake_group" and response.json()["group_number"] == 1
        assert len(state["writes"]) == 1


def test_several_intakes_save_together_in_one_insert(provider):
    from backend.tests.test_schedule_preview import add_lesson
    settings, state = provider
    add_lesson(state, 800, uid(3))
    multi = {"week_start": WEEK["week_start"], "intake_ids": [uid(1), uid(3)]}
    with client_for(settings) as client:
        data = generate(client, multi)
        body = {**save_body(data), "intake_ids": data["intake_ids"]}
        # The same classes saved under a single intake's scope are refused (different revision).
        single = client.post(SAVE, json={**save_body(data), "intake_id": uid(1)})
        assert single.status_code == 409 and detail(single)["code"] == "PREVIEW_STALE" and not state["writes"]
        response = client.post(SAVE, json=body)
        assert response.status_code == 201, response.text
        saved = response.json()
        assert saved["scope"] == "intakes" and saved["intake_id"] is None and saved["intake_ids"] == [uid(1), uid(3)]
        assert saved["saved_count"] == 2 and len(state["writes"]) == 1 and len(state["writes"][0]["rows"]) == 2
        assert generate_status(client, multi) == "NO_PENDING_REQUIREMENTS"


def generate_status(client, body):
    return client.post("/api/schedules/generate", json=body).json()["status"]


def test_preview_is_stale_when_the_week_changes_or_scope_differs(provider):
    settings, state = provider
    with client_for(settings) as client:
        data = generate(client)
        scoped = client.post(SAVE, json=save_body(data, group_number=1))
        assert scoped.status_code == 409 and detail(scoped)["code"] == "PREVIEW_STALE"
        state["payload"]["rooms"][0]["capacity"] += 1
        changed = client.post(SAVE, json=save_body(data))
        assert changed.status_code == 409 and detail(changed)["code"] == "PREVIEW_STALE"
    assert not state["writes"]


def test_partial_duplicate_or_unknown_placements_are_rejected(provider):
    settings, state = provider
    with client_for(settings) as client:
        data = generate(client)
        body = save_body(data)
        duplicate = {**body, "placements": body["placements"] * 2}
        unknown = {**body, "placements": body["placements"] + [{**body["placements"][0], "occurrence_id": uid(4242)}]}
        swapped = {**body, "placements": [{**body["placements"][0], "occurrence_id": uid(4242)}]}
        for case in (duplicate, unknown, swapped):
            response = client.post(SAVE, json=case)
            assert response.status_code == 422 and detail(response)["code"] == "PLACEMENTS_INCOMPLETE"
    assert not state["writes"]


@pytest.mark.parametrize("change,reason", [
    ({"starts_at": "2026-11-09T00:00:00Z"}, "OUTSIDE_TEACHING_HOURS"),  # 08:00 in Kuala Lumpur
    ({"starts_at": "2026-11-15T03:00:00Z"}, "OUTSIDE_TEACHING_HOURS"),  # Sunday
    ({"starts_at": "2026-11-09T09:50:00Z"}, "OUTSIDE_TEACHING_HOURS"),  # Monday 17:50, runs past 18:00
    ({"starts_at": "2026-11-30T03:00:00Z"}, "OUTSIDE_HORIZON"),  # another week
    ({"room_id": uid(999)}, "ROOM_NOT_FOUND"),
])
def test_edited_placement_fails_revalidation_and_nothing_is_written(provider, change, reason):
    settings, state = provider
    with client_for(settings) as client:
        data = generate(client)
        body = save_body(data)
        body["placements"][0].update(change)
        response = client.post(SAVE, json=body)
        assert response.status_code == 409
        assert detail(response)["code"] == "PLACEMENT_CONFLICT" and reason in detail(response)["message"]
    assert not state["writes"]


@pytest.mark.parametrize("edit", [
    lambda body: body.pop("snapshot_revision"),
    lambda body: body.update(snapshot_revision="ABC"),
    lambda body: body.update(placements=[]),
    lambda body: body["placements"][0].update(starts_at="2026-11-09T03:00:00"),  # no timezone
    lambda body: body["placements"][0].update(lecturer_id=uid(1)),  # extra field
    lambda body: body.update(student_ids=[]),
    lambda body: body.update(week_start="2026-11-10"),
    lambda body: body.update(group_number=0),
])
def test_invalid_save_request_is_rejected_before_any_database_call(provider, edit):
    settings, state = provider
    with client_for(settings) as client:
        body = save_body(generate(client))
        calls = len(state["calls"])
        edit(body)
        assert client.post(SAVE, json=body).status_code == 422
        assert len(state["calls"]) == calls
    assert not state["writes"]


@pytest.mark.parametrize("status,body,http,code", [
    (409, {"code": "23505", "message": "PRIVATE-PROVIDER-TEXT"}, 409, "ALREADY_SAVED"),
    (400, {"code": "P0001", "message": "PRIVATE-PROVIDER-TEXT"}, 409, "SAVE_REJECTED_BY_DATABASE"),
    (400, {"code": "23514", "hint": "PRIVATE-PROVIDER-TEXT"}, 409, "SAVE_REJECTED_BY_DATABASE"),
    (403, {"code": "42501", "details": "PRIVATE-PROVIDER-TEXT"}, 502, "DATABASE_PERMISSION_DENIED"),
    (500, "<html>PRIVATE-PROVIDER-TEXT</html>", 502, "DATABASE_UNAVAILABLE"),
    (201, [], 502, "SAVE_UNCONFIRMED"),
    # The save-audit migration is not applied: PostgREST does not know created_by.
    (400, {"code": "PGRST204", "message": "PRIVATE-PROVIDER-TEXT"}, 503, "AUDIT_NOT_INSTALLED"),
    (400, {"code": "42703", "message": "PRIVATE-PROVIDER-TEXT"}, 503, "AUDIT_NOT_INSTALLED"),
])
def test_database_write_errors_are_safe_and_release_the_slot(provider, traces, status, body, http, code):  # noqa: F811
    settings, state = provider
    state.update(write_status=status, write_body=(body if isinstance(body, str) else json.dumps(body)).encode())
    with client_for(settings) as client:
        response = client.post(SAVE, json=save_body(generate(client)))
        assert response.status_code == http and detail(response)["code"] == code
        assert detail(response)["request_id"] == response.headers["x-request-id"]
        assert "PRIVATE-PROVIDER-TEXT" not in response.text + json.dumps(traces)
        assert client.post("/api/schedules/generate", json=WEEK).status_code == 200


def test_write_timeout_reports_unknown_outcome(provider):
    settings, state = provider
    settings.supabase.timeout_seconds = 1
    state["write_delay"] = 2
    with client_for(settings) as client:
        response = client.post(SAVE, json=save_body(generate(client)))
        assert response.status_code == 504 and detail(response)["code"] == "SAVE_OUTCOME_UNKNOWN"


def test_save_and_generation_share_one_slot(provider, monkeypatch):
    settings, state = provider
    started, release = Event(), Event()
    real_solve = preview.solve_weekly_schedule

    def waiting_solver(*args):
        started.set()
        assert release.wait(5)
        return real_solve(*args)

    with client_for(settings) as client:
        body = save_body(generate(client))
        monkeypatch.setattr(preview, "solve_weekly_schedule", waiting_solver)
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(client.post, "/api/schedules/generate", json=WEEK)
            try:
                assert started.wait(5)
                busy = client.post(SAVE, json=body)
                assert busy.status_code == 429 and detail(busy)["code"] == "GENERATION_BUSY"
                assert busy.headers["retry-after"] == "2"
            finally:
                release.set()
            assert future.result(timeout=5).status_code == 200
        assert not state["writes"]
        assert client.post(SAVE, json=body).status_code == 201


@pytest.mark.parametrize("case", ["production", "remote", "origin", "forwarded"])
def test_save_access_rules_match_preview(provider, case):
    settings, state = provider
    with client_for(settings) as client:
        body = save_body(generate(client))
    state["calls"].clear()
    peer, headers = ("127.0.0.1", 51000), {}
    if case == "production":
        settings.app.environment = "production"
    elif case == "remote":
        peer = ("192.0.2.10", 51000)
    elif case == "origin":
        headers = {"Origin": "https://attacker.example"}
    else:
        headers = {"X-Forwarded-For": "127.0.0.1"}
    with TestClient(as_admin(create_app(settings)), base_url=BASE, client=peer, headers=headers) as client:
        assert client.post(SAVE, json=body).status_code == (404 if case == "production" else 403)
    assert not state["calls"] and not state["writes"]


def test_save_is_traced_without_private_values_and_documented(provider, traces):  # noqa: F811
    settings, state = provider
    with client_for(settings) as client:
        response = client.post(SAVE, json=save_body(generate(client)))
        assert response.status_code == 201
        trace_id = response.headers["x-request-id"]
        events = [item for item in traces if item["request_id"] == trace_id]
        assert [item["event"] for item in events if item["event"].startswith("save_")] == [
            "save_started", "save_validated", "save_completed"]
        assert next(item for item in events if item["event"] == "save_completed")["saved_count"] == 1
        assert events[-1]["event"] == "request_completed" and events[-1]["http_status"] == 201
        schema = client.get("/openapi.json").json()
        assert "post" in schema["paths"][SAVE] and "SaveRequest" in schema["components"]["schemas"]
    output = json.dumps(traces)
    for private in ("student_ids", "intake_id", "occurrence_id", "sb_secret_snapshot_test"):
        assert private not in output
