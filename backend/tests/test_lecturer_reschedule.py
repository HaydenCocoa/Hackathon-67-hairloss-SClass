"""Lecturer rescheduling after the 12 November 2026 fix (docs/backend/lecturer-reschedule-review.md).

Covers the five areas fixed: opening time from the config, the configured room policy and auditorium
rule, the move as one database function call (no direct writes), safe error text, and (in
test_auth.py) the real intake code and group size. Reuses the fake Supabase of test_admin_reschedule.py,
which feeds the real loader, validator and candidate generator. The class to move (MOVING) is a 90-minute
lecture of lecturer L1, intake I1 group 1 (3 students), on Monday of the week after next, 09:00 in R1.
"""

from datetime import timedelta

import pytest
from fastapi import HTTPException

from backend.app.auth import SessionUser
from backend.app.lecturer import safe_database_error
from backend.tests.test_admin_reschedule import (  # noqa: F401  (supabase is a pytest fixture)
    ADMIN, AUD, L1, L2, LAB, MONDAY, MOVING, R1, R2, SMALL, _time, at, client, supabase,
)

LECTURER = SessionUser(role="lecturer", name="Lee", profile_id=L1, home="/lecturer", auth_user_id="lee-auth")
OTHER = SessionUser(role="lecturer", name="Other", profile_id=L2, home="/lecturer", auth_user_id="other-auth")


def day(offset):
    return (MONDAY + timedelta(days=offset)).isoformat()


def patch(c, day_offset, hhmm, room, reason=None, lecturer=L1, session_id=MOVING):
    body = {"session_date": day(day_offset), "start_time": hhmm, "room_id": room}
    if reason is not None:
        body["reason"] = reason
    return c.patch(f"/api/lecturers/{lecturer}/sessions/{session_id}", json=body)


def test_a_valid_move_is_one_database_function_call_as_the_lecturer(supabase):
    settings, state = supabase
    with client(settings, LECTURER) as c:
        response = patch(c, 2, "13:00", R2)
    assert response.status_code == 200, response.text
    [call] = state["rpc"]  # no direct PATCH of class_sessions, no separate history insert
    assert call["path"] == "/rest/v1/rpc/lecturer_reschedule_class"
    assert call["authorization"] == "Bearer admin-access-token"  # the logged-in user's token: auth.uid()
    body = call["body"]
    assert body["session_id"] == MOVING and body["new_room"] == R2 and body["expected_room"] == R1
    assert _time(body["expected_start"]) == at(0, "09:00") and _time(body["new_start"]) == at(2, "13:00")
    assert body["change_reason"] == "No reason given"


def test_the_reason_is_passed_on_and_admins_use_the_admin_function(supabase):
    settings, state = supabase
    with client(settings, LECTURER) as c:
        assert patch(c, 2, "13:00", R2, reason="  Conference  ").status_code == 200
    with client(settings, ADMIN) as c:
        assert patch(c, 2, "13:00", R2).status_code == 200
    assert state["rpc"][0]["body"]["change_reason"] == "Conference"
    assert state["rpc"][1]["path"] == "/rest/v1/rpc/admin_reschedule_class"


@pytest.mark.parametrize("day_offset,hhmm,room,status,text", [
    # Opening time comes from the config (08:30), not the old hard-coded 08:00.
    (2, "08:00", R2, 422, "opening window"),
    (2, "08:29", R2, 422, "opening window"),
    (4, "16:45", R2, 422, "opening window"),     # 90 minutes would end after 18:00
    (5, "10:00", R2, 422, "opening window"),     # Saturday
    # Room policy from the config, and the auditorium rule.
    (2, "13:00", LAB, 422, "room type is not permitted"),               # a lecture may not use a lab
    (2, "13:00", AUD, 422, "kept for classes"),        # kept for classes no other room can seat
    (2, "13:00", SMALL, 422, "seat"),            # too small for 3 students
])
def test_opening_hours_and_room_rules_follow_the_config(supabase, day_offset, hhmm, room, status, text):
    settings, state = supabase
    with client(settings, LECTURER) as c:
        response = patch(c, day_offset, hhmm, room)
    assert response.status_code == status, response.text
    assert text in response.json()["detail"]["message"].lower()
    assert state["rpc"] == []


def test_08_30_is_now_a_valid_start(supabase):
    settings, state = supabase
    with client(settings, LECTURER) as c:
        response = patch(c, 3, "08:30", R2)
    assert response.status_code == 200, response.text
    assert _time(state["rpc"][0]["body"]["new_start"]) == at(3, "08:30")


@pytest.mark.parametrize("day_offset,hhmm,room,kind", [
    (2, "10:00", R1, "room"),        # R1 busy Wed 10:00-11:00
    (2, "08:30", R1, "room"),        # ends 10:00, no 15-minute gap before that class
    (3, "14:00", R2, "lecturer"),    # L1 teaches Thu 14:00-15:00
    (1, "09:00", R1, "student"),     # a student is also in intake I2's Tue 09:00 class
])
def test_clashes_are_listed_and_nothing_is_written(supabase, day_offset, hhmm, room, kind):
    settings, state = supabase
    with client(settings, LECTURER) as c:
        response = patch(c, day_offset, hhmm, room)
    assert response.status_code == 409, response.text
    assert kind in [conflict["type"] for conflict in response.json()["detail"]["conflicts"]]
    assert state["rpc"] == []


def test_another_lecturers_class_is_refused(supabase):
    settings, state = supabase
    with client(settings, OTHER) as c:
        assert patch(c, 2, "13:00", R2, lecturer=L2).status_code == 403
        assert patch(c, 2, "13:00", R2, lecturer=L1).status_code == 403
    assert state["rpc"] == []


@pytest.mark.parametrize("provider_code,status,text", [
    ("23P01", 409, "booked that room or time"),
    ("40001", 409, "changed by someone else"),
    ("42501", 403, "your own classes"),
    ("PGRST202", 503, "202611120004"),
    ("XX000", 502, "could not move the class"),
])
def test_database_function_errors_are_safe(supabase, provider_code, status, text):
    settings, state = supabase
    state["rpc_reply"] = (400, {"code": provider_code, "message": "secret provider text", "details": "row 42"})
    with client(settings, LECTURER) as c:
        response = patch(c, 2, "13:00", R2)
    assert response.status_code == status and text in response.json()["detail"]["message"]
    assert "secret provider text" not in response.text and "row 42" not in response.text


def test_read_and_internal_errors_never_show_provider_or_exception_text():
    read = safe_database_error(HTTPException(502, "Supabase could not read 'rooms' (HTTP 500)."))
    assert read.status_code == 502 and "rooms" not in read.detail["message"] and read.detail["conflicts"] == []
    crash = safe_database_error(RuntimeError("password=hunter2"))
    assert crash.status_code == 500 and "hunter2" not in str(crash.detail)


def test_suggestions_use_the_config_hours_and_suitable_rooms_only(supabase):
    settings, state = supabase
    with client(settings, LECTURER) as c:
        response = c.get(f"/api/lecturers/{L1}/sessions/{MOVING}/suggestions",
                         params={"date": day(2), "time": "08:00", "flex_days": 0, "limit": 20})
        weekend = c.get(f"/api/lecturers/{L1}/sessions/{MOVING}/suggestions",
                        params={"date": day(5), "time": "10:00", "flex_days": 0})
    assert response.status_code == 200, response.text
    slots = response.json()
    assert slots and all(slot["start_time"] >= "08:30" and slot["end_time"] <= "18:00" for slot in slots)
    assert slots[0]["start_time"] == "08:30"  # the nearest time to 08:00 that the config allows
    assert {slot["room_id"] for slot in slots} <= {R1, R2}  # never the lab, auditorium, small or inactive room
    # Wed: R1 is busy 10:00-11:00, so R1 is never offered within 15 minutes of it.
    for slot in slots:
        if slot["room_id"] == R1:
            assert slot["end_time"] <= "09:45" or slot["start_time"] >= "11:15"
    assert weekend.status_code == 200 and weekend.json() == []
    assert state["rpc"] == []
