"""Admin rescheduling: GET /api/admin/timetable/{id}/availability and POST .../reschedule.

A small fake Supabase (PostgREST filters eq/in/lt/gt, select projection, the reschedule RPC) feeds the
real loader, validator and candidate generator. Dates are computed from today, so the data stays in
the future: the class to move is on Monday of the week after next, 09:00-10:30 campus time.
"""

import json
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from backend.app.auth import SessionUser, get_session
from backend.app.config import load_settings
from backend.app.main import create_app

KL = ZoneInfo("Asia/Kuala_Lumpur")
uid = lambda n: str(UUID(int=n))  # noqa: E731
MONDAY = (lambda today: today - timedelta(days=today.weekday()) + timedelta(days=14))(datetime.now(KL).date())
ADMIN = SessionUser(role="admin", name="Ada Admin", profile_id=uid(900), home="/admin", auth_user_id=uid(901))
STUDENT = SessionUser(role="student", name="Sam", profile_id=uid(902), home="/student", auth_user_id=uid(903), code="TP1")
R1, R2, LAB, AUD, SMALL, OFF = (uid(n) for n in range(11, 17))
I1, I2, I3 = uid(21), uid(22), uid(23)
L1, L2 = uid(31), uid(32)
MOVING, CANCELLED, PAST = uid(41), uid(42), uid(43)


def at(day_offset, hhmm, base=None):
    h, m = map(int, hhmm.split(":"))
    day = (base or MONDAY) + timedelta(days=day_offset)
    return datetime(day.year, day.month, day.day, h, m, tzinfo=KL).astimezone(timezone.utc)


def session(n, section, intake, lecturer, room, start, minutes, kind="lecture", status="scheduled"):
    return {"id": uid(n) if isinstance(n, int) else n, "section_id": uid(section), "room_id": room,
            "starts_at": start.isoformat(), "ends_at": (start + timedelta(minutes=minutes)).isoformat(),
            "status": status, "group_number": 1, "intake_id": intake, "lecturer_id": lecturer, "course_id": uid(section + 500),
            "course_code": f"C{section}", "course_name": f"Course {section}", "course_type": kind, "duration_minutes": minutes}


def tables():
    past = datetime.now(timezone.utc) - timedelta(days=1)
    return {
        "rooms": [
            {"id": R1, "name": "R1", "building": "A", "capacity": 40, "room_type": "classroom", "is_active": True},
            {"id": R2, "name": "R2", "building": "A", "capacity": 40, "room_type": "classroom", "is_active": True},
            {"id": LAB, "name": "LAB", "building": "B", "capacity": 40, "room_type": "lab", "is_active": True},
            {"id": AUD, "name": "AUD", "building": "C", "capacity": 300, "room_type": "auditorium", "is_active": True},
            {"id": SMALL, "name": "SMALL", "building": "A", "capacity": 2, "room_type": "classroom", "is_active": True},
            {"id": OFF, "name": "OFF", "building": "A", "capacity": 40, "room_type": "classroom", "is_active": False},
        ],
        "lecturers": [{"id": L1}, {"id": L2}],
        "student_intakes": [
            *({"student_id": uid(s), "intake_id": I1, "group_number": 1} for s in (61, 62, 63)),
            *({"student_id": uid(s), "intake_id": I2, "group_number": 1} for s in (63, 64)),  # 63 is in both intakes
            {"student_id": uid(65), "intake_id": I3, "group_number": 1},
        ],
        "class_session_details": [
            session(MOVING, 101, I1, L1, R1, at(0, "09:00"), 90),                      # the class to move
            session(51, 102, I2, L2, R2, at(1, "09:00"), 60, "tutorial"),              # shares student 63
            session(52, 103, I3, L2, R1, at(2, "10:00"), 60),                          # R1 busy Wed 10-11
            session(53, 104, I3, L1, R2, at(3, "14:00"), 60),                          # lecturer L1 busy Thu 14-15
            session(CANCELLED, 105, I1, L1, R2, at(0, "13:00"), 60, status="cancelled"),
            session(PAST, 106, I1, L1, R2, past, 60),
        ],
        "class_sessions": [],
        "teaching_occurrence_details": [],
        "meeting_sessions": [{"id": uid(71), "lecturer_id": L2, "room_id": LAB, "status": "scheduled",
                              "starts_at": at(4, "11:00").isoformat(), "ends_at": at(4, "12:00").isoformat()}],
        "meeting_students": [{"meeting_id": uid(71), "student_id": uid(61)}],          # Fri 11-12, student 61
    }


def _time(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def matches(row, key, expression):
    value = row.get(key)
    if expression.startswith("eq."):
        return str(value) == expression[3:]
    if expression.startswith("in.("):
        return str(value) in expression[4:-1].replace('"', "").split(",")
    if expression[:3] in ("lt.", "gt."):
        left, right = _time(value), _time(expression[3:])
        return left < right if expression.startswith("lt.") else left > right
    return True


@pytest.fixture
def supabase(monkeypatch):
    state = {"tables": tables(), "rpc": [], "rpc_reply": (200, None)}
    for row in state["tables"]["class_session_details"]:
        state["tables"]["class_sessions"].append({"id": row["id"], "occurrence_id": None})

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            parsed = urlsplit(self.path)
            params = parse_qs(parsed.query)
            rows = list(state["tables"].get(parsed.path.removeprefix("/rest/v1/"), []))
            for key, values in params.items():
                if key in ("select", "order", "limit", "offset"):
                    continue
                rows = [row for row in rows if all(matches(row, key, value) for value in values)]
            select = params.get("select", ["*"])[0]
            if select != "*":
                rows = [{key: row.get(key) for key in select.split(",")} for row in rows]
            offset, limit = int(params.get("offset", ["0"])[0]), int(params.get("limit", ["1000"])[0])
            self.reply(200, rows[offset:offset + limit])

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            state["rpc"].append({"path": urlsplit(self.path).path, "body": body, "authorization": self.headers.get("Authorization")})
            self.reply(*state["rpc_reply"])

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    settings = load_settings()
    settings.supabase.url_env, settings.supabase.key_env = "RESCHEDULE_TEST_URL", "RESCHEDULE_TEST_KEY"
    monkeypatch.setenv("RESCHEDULE_TEST_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("RESCHEDULE_TEST_KEY", "sb_secret_reschedule_test")
    yield settings, state
    server.shutdown()
    server.server_close()


def client(settings, user=ADMIN):
    app = create_app(settings)

    async def logged_in(request: Request):
        request.state.access_token = "admin-access-token"
        return user
    app.dependency_overrides[get_session] = logged_in if user else (lambda: None)
    return TestClient(app, base_url="http://127.0.0.1:8000")


def availability(c, day_offset, start=None, session_id=MOVING):
    params = {"date": (MONDAY + timedelta(days=day_offset)).isoformat(), **({"start": start} if start else {})}
    return c.get(f"/api/admin/timetable/{session_id}/availability", params=params)


def test_rooms_are_explained_and_the_time_grid_follows_opening_hours(supabase):
    settings, _ = supabase
    with client(settings) as c:
        response = availability(c, 2, "10:00")  # Wednesday: R1 has another class 10:00-11:00
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert (data["student_count"], data["status"], data["duration_minutes"]) == (3, "scheduled", 90)
    rooms = {room["name"]: room for room in data["rooms"]}
    assert [name for name, room in rooms.items() if room["suitable"]] == ["R1", "R2"]
    assert {name: [i["code"] for i in rooms[name]["issues"]] for name in ("AUD", "LAB", "OFF", "SMALL")} == {
        "AUD": ["ROOM_RESERVED_FOR_LARGE_CLASSES"], "LAB": ["ROOM_TYPE_MISMATCH"], "OFF": ["ROOM_INACTIVE"],
        "SMALL": ["ROOM_TOO_SMALL"],
    }
    selected = data["selected"]
    assert (selected["start"], selected["end"], selected["time_issues"]) == ("10:00", "11:30", [])
    assert selected["available_room_ids"] == [R2]
    assert [i["code"] for i in selected["room_issues"][R1]] == ["ROOM_CONFLICT"]
    assert set(selected["room_issues"]) == {R1, LAB, AUD, SMALL, OFF}
    # 90-minute class, 08:30-18:00, every 15 minutes: 08:30 ... 16:30.
    assert (data["step_minutes"], data["duration_minutes"]) == (15, 90)
    assert [s["start"] for s in data["slots"]][:2] == ["08:30", "08:45"] and data["slots"][-1]["start"] == "16:30"
    slot = {s["start"]: s["free_room_ids"] for s in data["slots"]}
    assert slot["10:00"] == [R2] and sorted(slot["13:00"]) == sorted([R1, R2])
    # The 15-minute gap around R1's 10:00-11:00 class: a class must end by 09:45 or start from 11:15.
    assert R1 not in slot["08:30"]  # would end 10:00, exactly when the other class starts
    assert R1 not in slot["11:00"] and R1 in slot["11:15"]


@pytest.mark.parametrize("day_offset,start,code", [
    (3, "14:00", "LECTURER_CONFLICT"),          # Thursday: the lecturer teaches elsewhere 14:00-15:00
    (4, "11:00", "STUDENT_CONFLICT"),           # Friday: a student is in a meeting 11:00-12:00
    (1, "09:00", "STUDENT_CONFLICT"),           # Tuesday: a student shared with another intake has a class
    (2, "17:00", "OUTSIDE_TEACHING_HOURS"),     # would end 18:30
])
def test_time_wide_problems_make_every_room_unavailable(supabase, day_offset, start, code):
    settings, _ = supabase
    with client(settings) as c:
        selected = availability(c, day_offset, start).json()["selected"]
    assert code in [issue["code"] for issue in selected["time_issues"]]
    assert selected["available_room_ids"] == []


def test_own_time_stays_free_weekends_are_closed_and_other_weeks_work(supabase):
    settings, _ = supabase
    with client(settings) as c:
        own = availability(c, 0, "09:00").json()
        weekend = availability(c, 5).json()
        next_week = availability(c, 7, "09:00").json()
    assert R1 in own["selected"]["available_room_ids"]  # its own booking does not block it
    assert "09:00" in [s["start"] for s in own["slots"]]
    assert weekend["slots"] == [] and weekend["selected"] is None
    assert sorted(next_week["selected"]["available_room_ids"]) == sorted([R1, R2])


@pytest.mark.parametrize("session_id,params,status,code", [
    (uid(999), {}, 404, "CLASS_NOT_FOUND"),
    (CANCELLED, {}, 409, "CLASS_NOT_ACTIVE"),
    (PAST, {}, 409, "CLASS_STARTED"),
    (MOVING, {"start": "9:00"}, 422, None),
    (MOVING, {"date": "2026-02-30"}, 422, None),
    ("not-a-uuid", {}, 422, None),
])
def test_availability_errors(supabase, session_id, params, status, code):
    settings, _ = supabase
    with client(settings) as c:
        query = {"date": MONDAY.isoformat(), **params}
        response = c.get(f"/api/admin/timetable/{session_id}/availability", params=query)
    assert response.status_code == status, response.text
    if code:
        assert response.json()["detail"]["code"] == code and response.json()["detail"]["request_id"] != "-"


def test_only_logged_in_admins_can_use_it(supabase):
    settings, state = supabase
    with client(settings, STUDENT) as c:
        assert availability(c, 2, "10:00").json()["detail"]["code"] == "ADMIN_REQUIRED"
    with client(settings, None) as c:
        assert availability(c, 2, "10:00").status_code == 401
        assert c.post(f"/api/admin/timetable/{MOVING}/reschedule", json=move()).status_code == 401
    assert state["rpc"] == []


def move(day_offset=2, hhmm="13:00", room=R2, **changes):
    return {"expected_starts_at": at(0, "09:00").isoformat(), "expected_room_id": R1,
            "starts_at": at(day_offset, hhmm).isoformat(), "room_id": room, "reason": "Lecturer request", **changes}


def test_a_valid_move_is_checked_then_saved_by_the_database_function(supabase):
    settings, state = supabase
    with client(settings) as c:
        response = c.post(f"/api/admin/timetable/{MOVING}/reschedule", json=move())
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "RESCHEDULED" and data["room_id"] == R2
    assert _time(data["ends_at"]) - _time(data["starts_at"]) == timedelta(minutes=90)
    [call] = state["rpc"]
    assert call["path"] == "/rest/v1/rpc/admin_reschedule_class"
    assert call["authorization"] == "Bearer admin-access-token"  # the admin's own token: auth.uid() is the admin
    assert call["body"]["session_id"] == MOVING and call["body"]["new_room"] == R2
    assert _time(call["body"]["expected_start"]) == at(0, "09:00") and call["body"]["expected_room"] == R1
    assert _time(call["body"]["new_start"]) == at(2, "13:00") and call["body"]["change_reason"] == "Lecturer request"


@pytest.mark.parametrize("reason", [None, "", "   ", "omit"])
def test_the_reason_is_optional_and_recorded_as_no_reason_given(supabase, reason):
    settings, state = supabase
    body = move(reason=reason)
    if reason == "omit":
        del body["reason"]
    with client(settings) as c:
        response = c.post(f"/api/admin/timetable/{MOVING}/reschedule", json=body)
    assert response.status_code == 200, response.text
    [call] = state["rpc"]
    assert call["body"]["change_reason"] == "No reason given"


def test_a_cross_site_origin_cannot_reschedule_but_this_site_can(supabase):
    settings, state = supabase
    with client(settings) as c:
        rejected = c.post(f"/api/admin/timetable/{MOVING}/reschedule", json=move(),
                          headers={"Origin": "https://attacker.example"})
        assert rejected.status_code == 403 and rejected.json()["detail"]["code"] == "ORIGIN_NOT_ALLOWED"
        assert state["rpc"] == []
        # Behind Vercel's proxy the browser's host arrives as X-Forwarded-Host.
        allowed = c.post(f"/api/admin/timetable/{MOVING}/reschedule", json=move(),
                         headers={"Origin": "https://sclass.example", "X-Forwarded-Host": "sclass.example"})
        assert allowed.status_code == 200, allowed.text


@pytest.mark.parametrize("body,status,code", [
    (move(2, "10:00", R1), 409, "SLOT_UNAVAILABLE"),                 # R1 is busy
    (move(3, "14:00", R2), 409, "SLOT_UNAVAILABLE"),                 # lecturer busy
    (move(2, "13:00", LAB), 409, "SLOT_UNAVAILABLE"),                # wrong room type
    (move(2, "13:00", R2, expected_room_id=R2), 409, "CLASS_CHANGED"),
    (move(0, "09:00", R1), 422, "NO_CHANGE"),
    ({**move(), "reason": "x" * 501}, 422, None),                   # reason too long
    ({**move(), "starts_at": "2030-01-07T09:00:00"}, 422, None),    # no timezone
    ({**move(), "starts_at": at(2, "13:00").replace(second=30).isoformat()}, 422, "START_NOT_WHOLE_MINUTE"),
    ({**move(), "extra": 1}, 422, None),
])
def test_invalid_moves_never_reach_the_database_function(supabase, body, status, code):
    settings, state = supabase
    with client(settings) as c:
        response = c.post(f"/api/admin/timetable/{MOVING}/reschedule", json=body)
    assert response.status_code == status, response.text
    if code:
        assert response.json()["detail"]["code"] == code
    if code == "SLOT_UNAVAILABLE":
        assert response.json()["detail"]["issues"]
    assert state["rpc"] == []


@pytest.mark.parametrize("provider_code,status,code", [
    ("23P01", 409, "SLOT_TAKEN"), ("40001", 409, "CLASS_CHANGED"), ("42883", 503, "MIGRATION_MISSING"),
    ("42703", 503, "MIGRATION_MISSING"), ("XX000", 502, "DATABASE_REJECTED"),
])
def test_database_function_errors_are_explained(supabase, provider_code, status, code):
    settings, state = supabase
    state["rpc_reply"] = (400, {"code": provider_code, "message": "private provider text"})
    with client(settings) as c:
        response = c.post(f"/api/admin/timetable/{MOVING}/reschedule", json=move())
    assert response.status_code == status and response.json()["detail"]["code"] == code
    assert "private provider text" not in response.text
