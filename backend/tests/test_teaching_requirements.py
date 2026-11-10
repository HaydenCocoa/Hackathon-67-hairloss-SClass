import asyncio
import json
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from time import sleep
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend.app.config import load_settings
from backend.app.scheduling.requirements import TeachingPlanInput, load_weekly_requirements
from backend.app.student import Supabase


def requirement(number=1, **changes):
    row = {
        "occurrence_id": str(UUID(int=number)), "plan_id": str(UUID(int=20)),
        "section_id": str(UUID(int=21)), "original_week_start": "2026-11-09",
        "target_week_start": "2026-11-09", "teaching_week_number": 1,
        "occurrence_number": number, "requirement_status": "required",
        "timezone": "Asia/Kuala_Lumpur", "class_session_id": None,
        "booking_status": None, "starts_at": None, "room_id": None,
        "needs_scheduling": True, "group_number": 1, "required_room_type": "lab",
        "intake_id": str(UUID(int=22)), "lecturer_id": str(UUID(int=23)),
        "course_id": str(UUID(int=24)), "course_code": "CS1",
        "course_name": "Subject", "course_type": "lab", "duration_minutes": 120,
    }
    row.update(changes)
    return row


@pytest.fixture
def database_server(monkeypatch):
    settings = load_settings().supabase
    settings.url_env = "REQUIREMENTS_TEST_URL"
    settings.key_env = "REQUIREMENTS_TEST_KEY"
    state = {"rows": [], "calls": [], "status": 200, "body": None,
             "ignore_offset": False, "delay": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urlsplit(self.path)
            query = parse_qs(url.query)
            state["calls"].append({"path": url.path, "query": query, "headers": dict(self.headers)})
            sleep(state["delay"])
            status = state["status"] if url.path == "/rest/v1/teaching_occurrence_details" else 501
            rows = state["rows"]
            rows = [r for r in rows if r.get("target_week_start") == query["target_week_start"][0][3:]]
            if query.get("needs_scheduling") == ["eq.true"]:
                rows = [r for r in rows if r.get("needs_scheduling")]
            offset = 0 if state["ignore_offset"] else int(query["offset"][0])
            # Simulate a provider row cap smaller than our requested page size.
            body = state["body"] if state["body"] is not None else json.dumps(rows[offset:offset + 1]).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv(settings.url_env, f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv(settings.key_env, "sb_secret_requirements_test")
    yield settings, state
    server.shutdown()
    server.server_close()
    thread.join()


def read_week(settings, week=date(2026, 11, 9), **options):
    async def run():
        async with httpx.AsyncClient() as client:
            return await load_weekly_requirements(Supabase(settings, client), week, **options)
    return asyncio.run(run())


def test_plan_defines_a_weekly_recurrence_without_room_or_time():
    plan = TeachingPlanInput(section_id=UUID(int=21), first_week_start="2026-11-09", week_count=12)
    assert plan.occurrences_per_week == 1
    assert plan.timezone == "Asia/Kuala_Lumpur"
    assert plan.model_dump(mode="json")["first_week_start"] == "2026-11-09"


@pytest.mark.parametrize("changes", [
    {"first_week_start": "2026-11-10"}, {"week_count": 0}, {"week_count": True},
    {"occurrences_per_week": 0}, {"timezone": "Invalid/Timezone"},
    {"starts_at": "09:00"}, {"section_id": "not-a-uuid"},
])
def test_invalid_recurrence_input_is_rejected(changes):
    payload = {"section_id": str(UUID(int=21)), "first_week_start": "2026-11-09", "week_count": 12}
    payload.update(changes)
    with pytest.raises(ValidationError):
        TeachingPlanInput.model_validate(payload)


def test_weekly_reader_paginates_and_resolves_pending_and_booked_requirements(database_server):
    settings, state = database_server
    state["rows"] = [requirement(), requirement(2, needs_scheduling=False, booking_status="scheduled",
        class_session_id=str(UUID(int=30)), room_id=str(UUID(int=31)), starts_at="2026-11-09T09:17:00+08:00"),
        requirement(3, requirement_status="cancelled", needs_scheduling=False),
        requirement(4, target_week_start="2026-11-16")]
    rows = read_week(settings)
    assert [r.occurrence_id for r in rows] == [UUID(int=1), UUID(int=2), UUID(int=3)]
    assert rows[1].starts_at.isoformat() == "2026-11-09T09:17:00+08:00"
    assert [c["query"]["offset"] for c in state["calls"]] == [["0"], ["1"], ["2"], ["3"]]
    assert all(c["headers"]["apikey"] == "sb_secret_requirements_test" for c in state["calls"])
    assert all(c["query"]["order"] == ["occurrence_id.asc"] for c in state["calls"])
    assert [r.occurrence_id for r in read_week(settings, pending_only=True)] == [UUID(int=1)]


def test_makeup_is_loaded_by_target_week_without_changing_original_identity(database_server):
    settings, state = database_server
    state["rows"] = [requirement(target_week_start="2026-12-07")]
    assert read_week(settings) == []
    rows = read_week(settings, date(2026, 12, 7), pending_only=True)
    assert rows[0].occurrence_id == UUID(int=1)
    assert rows[0].original_week_start == date(2026, 11, 9)


def test_invalid_week_is_rejected_before_reading_database(database_server):
    settings, state = database_server
    for week in (date(2026, 11, 10), datetime(2026, 11, 9)):
        with pytest.raises(ValueError, match="Monday date"):
            read_week(settings, week)
    assert not state["calls"]


def test_reader_reports_missing_migration_as_failure_not_empty_demand(database_server):
    settings, state = database_server
    state["status"] = 404
    state["body"] = b'{"message":"relation missing"}'
    with pytest.raises(HTTPException) as error:
        read_week(settings)
    assert error.value.status_code == 502


def test_reader_rejects_malformed_requirement(database_server):
    settings, state = database_server
    bad = requirement()
    del bad["duration_minutes"]
    state["rows"] = [bad]
    with pytest.raises(HTTPException, match="invalid teaching requirements"):
        read_week(settings)


def test_reader_does_not_loop_or_duplicate_if_provider_ignores_pagination(database_server):
    settings, state = database_server
    state.update(rows=[requirement()], ignore_offset=True)
    with pytest.raises(HTTPException, match="inconsistent teaching requirements"):
        read_week(settings)
    assert len(state["calls"]) == 2


def test_reader_rejects_response_from_wrong_week(database_server):
    settings, state = database_server
    state["body"] = json.dumps([requirement(target_week_start="2026-11-16")]).encode()
    with pytest.raises(HTTPException, match="inconsistent teaching requirements"):
        read_week(settings)


def test_reader_reports_upstream_timeout(database_server):
    settings, state = database_server
    settings.timeout_seconds = 0.03
    state["delay"] = 0.15
    with pytest.raises(HTTPException) as error:
        read_week(settings)
    assert error.value.status_code == 504
