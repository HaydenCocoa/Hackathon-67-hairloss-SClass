"""Lecturer page API: own timetable, suggested free times, and moving one's own class.

Since 12 November 2026 (lecturer review re-check, docs/backend/lecturer-reschedule-review.md) a move
and the suggestions follow the same compulsory rules as generated timetables, by reusing the scheduling
engine through scheduling/reschedule.py: opening hours and closed dates from Config/config.json, the
configured room policy and the auditorium rule, capacity, the 15-minute gap, and no clash for the
room, the lecturer or any student (classes and meetings). The move itself is one database
transaction under the timetable lock: public.lecturer_reschedule_class (migration 202611120004) for
lecturers, public.admin_reschedule_class for admins acting on a lecturer's behalf.
"""

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from .auth import SessionUser, require_login, require_roles
from .config import Settings
from .scheduling.loader import SchedulingDataError
from .scheduling.candidates import CandidateGenerator
from .scheduling.reschedule import (CLASS_SELECT, NO_REASON_TEXT, MoveFailed, explain, free_room_ids,
                                    load_roster, load_target_snapshot, run_move_function, start_grid)
from .scheduling.validator import BookingValidator
# Shared, safe database client: errors carry no provider text (lecturer review, finding 7).
from .student import Supabase

logger = logging.getLogger(__name__)

# Classes are scheduled and shown in Malaysia time (UTC+8, no daylight saving).
MY_TZ = timezone(timedelta(hours=8))

# A class that is still going ahead. "rescheduled" = it was moved at least once.
ACTIVE_STATUSES = ("scheduled", "rescheduled")

STEP_MIN = 30  # suggested start times are every 30 minutes from each day's opening time

# Engine issue codes shown as a clash (409) rather than a rule the time or room breaks (422).
CLASH_TYPES = {"ROOM_CONFLICT": "room", "LECTURER_CONFLICT": "lecturer", "STUDENT_CONFLICT": "student"}


def day_start_utc(day: date) -> str:
    """Midnight at the start of a Malaysian calendar day, as the UTC instant the database compares against."""
    return datetime(day.year, day.month, day.day, tzinfo=MY_TZ).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SessionDetail(BaseModel):
    id: str
    session_date: str
    start_time: str
    end_time: str
    room_id: Optional[str] = None
    room_name: Optional[str] = None
    course_code: str
    course_type: str
    course_name: str
    intake_code: str
    group_number: int
    student_count: int
    duration_minutes: int
    required_room_type: str
    allowed_room_types: List[str] = []
    status: str
    moved: bool = False
    can_reschedule: bool = True

class RescheduleRequest(BaseModel):
    session_date: str
    start_time: str
    room_id: str
    reason: Optional[str] = None

LECTURER_OR_ADMIN = require_roles("lecturer", "admin")


def check_own_lecturer(session: SessionUser, lecturer_id: str) -> None:
    # Login: a lecturer may only use their own id; admins may use any.
    if session.role == "lecturer" and session.profile_id != lecturer_id:
        raise HTTPException(403, {"message": "You can only view and change your own classes.", "conflicts": []})


def parse_ts(value: str) -> datetime:
    """Parse a timestamp as Supabase prints it ("2026-11-11 09:00:00+00") into an aware datetime."""
    text = value.replace(" ", "T")
    if text.endswith("+00"):
        text += ":00"
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def day_start_utc_dt(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=MY_TZ)


async def without_removed(db: Supabase, rows: list[dict]) -> list[dict]:
    """Leave out classes that were removed (class_sessions.removed_at is set); they no longer occupy anything."""
    ids = [str(r["id"]) for r in rows if r.get("id")]
    if not ids:
        return rows
    gone = await db.get("class_sessions", [("select", "id"), ("removed_at", "not.is.null"), ("id", f"in.({','.join(ids)})")])
    removed = {str(g["id"]) for g in gone}
    return [r for r in rows if str(r.get("id")) not in removed]


async def group_facts(db: Supabase, rows: list[dict]) -> tuple[dict[str, str], dict[tuple[str, int], int]]:
    """Intake codes by intake id, and the real number of students in each (intake, group) shown.
    Restores the review fix that commit 00e0a83 replaced with "CS-2024" and 30."""
    groups = sorted({(str(r["intake_id"]), r["group_number"]) for r in rows if r.get("intake_id")})
    if not groups:
        return {}, {}
    intake_ids = sorted({intake for intake, _ in groups})
    intakes, *members = await asyncio.gather(
        db.get("intakes", [("select", "id,intake_code"), ("id", f"in.({','.join(intake_ids)})")]),
        *(db.get("student_intakes", [("select", "student_id"), ("intake_id", f"eq.{intake}"),
                                      ("group_number", f"eq.{group}")]) for intake, group in groups),
    )
    codes = {str(r["id"]): r["intake_code"] for r in intakes}
    return codes, {group: len(rows_) for group, rows_ in zip(groups, members)}


async def get_own_session(db: Supabase, lecturer_id: str, session_id: str) -> dict:
    """The class, if it exists, belongs to this lecturer and has not been cancelled."""
    rows = await db.get("class_session_details", [("select", CLASS_SELECT), ("id", f"eq.{session_id}")])
    rows = await without_removed(db, rows)
    if not rows:
        raise HTTPException(404, {"message": "Class not found.", "conflicts": []})
    if str(rows[0].get("lecturer_id")) != lecturer_id:
        raise HTTPException(403, {"message": "You can only change your own classes.", "conflicts": []})
    if rows[0].get("status") not in ACTIVE_STATUSES:
        raise HTTPException(409, {"message": "A cancelled class cannot be rescheduled.", "conflicts": []})
    return rows[0]


def refuse(status: int, message: str, conflicts: list | None = None) -> HTTPException:
    return HTTPException(status, {"message": message, "conflicts": conflicts or []})


def safe_database_error(exc: Exception) -> HTTPException:
    """A database or data problem as a safe {message, conflicts} reply (no provider or exception text)."""
    if isinstance(exc, HTTPException) and isinstance(exc.detail, dict):
        return exc
    if isinstance(exc, SchedulingDataError):
        logger.warning("lecturer scheduling data rejected: %s", exc.code)
        return refuse(502, "The timetable data could not be checked. Try again later.")
    if isinstance(exc, HTTPException):
        status = exc.status_code if exc.status_code in (502, 503, 504) else 502
        return refuse(status, {503: "The database is not configured.", 504: "The database did not answer in time. Try again."}
                      .get(status, "The database could not complete the request. Try again."))
    logger.error("lecturer request failed: %s", type(exc).__name__)
    return refuse(500, "Something went wrong. Nothing was changed.")


def create_lecturer_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["lecturer"])
    compatibility = settings.scheduling.room_compatibility

    def allowed_room_types(course_type: str) -> list[str]:
        """Room types this course type may use, from scheduling.room_compatibility (empty = none)."""
        return list(compatibility.get(course_type, ()))

    def database(request: Request) -> Supabase:
        try:
            return Supabase(settings.supabase, request.app.state.http_client)
        except HTTPException as exc:
            raise safe_database_error(exc) from exc

    @router.get("/rooms", response_model=List[dict], dependencies=[Depends(require_login)])
    async def get_rooms(request: Request):
        db = database(request)
        try:
            return await db.get("rooms", [("select", "*"), ("is_active", "eq.true")])
        except Exception as exc:
            raise safe_database_error(exc) from exc

    @router.get("/lecturers", response_model=List[dict])
    async def get_lecturers(request: Request, session: SessionUser = Depends(LECTURER_OR_ADMIN)):
        db = database(request)
        params = [("select", "id,full_name")]
        if session.role == "lecturer":
            params.append(("id", f"eq.{session.profile_id}"))  # a lecturer only sees themselves
        try:
            rows = await db.get("lecturers", params)
        except Exception as exc:
            raise safe_database_error(exc) from exc
        return [{"id": r["id"], "name": r["full_name"]} for r in rows]

    @router.get("/lecturers/{lecturer_id}/timetable", response_model=List[SessionDetail])
    async def get_lecturer_timetable(
        lecturer_id: str,
        request: Request,
        start: str = Query(...),
        end: Optional[str] = None,
        session: SessionUser = Depends(LECTURER_OR_ADMIN),
    ):
        check_own_lecturer(session, lecturer_id)
        # start/end are Malaysian dates (end inclusive), so the window is [start 00:00, end+1 00:00) in UTC+8.
        try:
            first_day = date.fromisoformat(start)
            last_day = date.fromisoformat(end) if end else None
        except ValueError:
            raise HTTPException(422, detail="start and end must be dates like 2026-11-09")
        db = database(request)
        query_params = [("select", "*,rooms(name)"), ("lecturer_id", f"eq.{lecturer_id}"),
                        ("starts_at", f"gte.{day_start_utc(first_day)}")]
        if last_day:
            query_params.append(("starts_at", f"lt.{day_start_utc(last_day + timedelta(days=1))}"))
        try:
            data = await without_removed(db, await db.get("class_session_details", query_params))
            intake_codes, group_sizes = await group_facts(db, data)
        except Exception as exc:
            raise safe_database_error(exc) from exc

        results = []
        now = datetime.now(timezone.utc)
        for s in data:
            starts_dt = parse_ts(s["starts_at"]).astimezone(MY_TZ)
            ends_dt = parse_ts(s["ends_at"]).astimezone(MY_TZ)
            allowed = allowed_room_types(s["course_type"])
            results.append({
                "id": s["id"],
                "session_date": starts_dt.strftime("%Y-%m-%d"),
                "start_time": starts_dt.strftime("%H:%M"),
                "end_time": ends_dt.strftime("%H:%M"),
                "room_id": s.get("room_id"),
                "room_name": s.get("rooms", {}).get("name") if s.get("rooms") else None,
                "course_code": s["course_code"],
                "course_type": s["course_type"],
                "course_name": s["course_name"],
                "intake_code": intake_codes.get(str(s.get("intake_id")), ""),
                "group_number": s["group_number"],
                "student_count": group_sizes.get((str(s.get("intake_id")), s["group_number"]), 0),
                "duration_minutes": s["duration_minutes"],
                "required_room_type": allowed[0] if allowed else "",
                "allowed_room_types": allowed,
                "status": s["status"],
                "moved": s["status"] == "rescheduled",
                "can_reschedule": s["status"] in ACTIVE_STATUSES and starts_dt > now,
            })
        return results

    async def suggest_slots(db: Supabase, moving: dict, wanted_day: date, wanted_min: int,
                            flex_days: int, limit: int) -> list[dict]:
        """Free times near the requested day and time, best first. Uses the scheduling engine's candidate
        ranges: opening hours and closed dates from the config, suitable rooms only (type, capacity,
        auditorium rule), the gap, and no room, lecturer or student clash."""
        now = datetime.now(timezone.utc)
        current_start = parse_ts(moving["starts_at"])
        duration = timedelta(minutes=moving["duration_minutes"])
        days = [(offset, wanted_day + timedelta(days=offset)) for offset in range(-flex_days, flex_days + 1)]
        days = [(o, d) for o, d in days if day_start_utc_dt(d + timedelta(days=1)) > now]
        if not days:
            return []
        students = await load_roster(db, moving)
        occurrence = UUID(str(moving["id"]))
        weeks: dict[date, tuple] = {}  # week start -> (snapshot, candidate ranges, rooms by id)
        candidates = []
        for offset, day in days:
            week = day - timedelta(days=day.weekday())
            if week not in weeks:
                snapshot = await load_target_snapshot(db, settings.scheduling, moving, students, day)
                ranges = CandidateGenerator(snapshot).generate(occurrence).ranges
                weeks[week] = (snapshot, ranges, {room.id: room for room in snapshot.rooms})
            snapshot, ranges, rooms = weeks[week]
            for start in start_grid(snapshot, day, duration, STEP_MIN):
                if start <= now or start == current_start:
                    continue
                free = sorted((rooms[room_id] for room_id in free_room_ids(ranges, start)),
                              key=lambda room: (room.capacity, room.name))  # the smallest room that fits first
                if not free:
                    continue
                room, local = free[0], start.astimezone(MY_TZ)
                minute = local.hour * 60 + local.minute
                candidates.append((abs(offset) * 1000 + abs(minute - wanted_min), {
                    "session_date": f"{day:%Y-%m-%d}", "start_time": f"{local:%H:%M}",
                    "end_time": f"{(start + duration).astimezone(MY_TZ):%H:%M}",
                    "room_id": str(room.id), "room_name": room.name, "building": room.building,
                    "capacity": room.capacity,
                }))
        candidates.sort(key=lambda c: c[0])

        def minutes(hhmm: str) -> int:
            return int(hhmm[:2]) * 60 + int(hhmm[3:5])

        chosen: list[dict] = []
        for _, slot in candidates:  # keep suggestions at least an hour apart on the same day
            if any(c["session_date"] == slot["session_date"] and abs(minutes(c["start_time"]) - minutes(slot["start_time"])) < 60
                   for c in chosen):
                continue
            chosen.append(slot)
            if len(chosen) == limit:
                break
        return chosen

    @router.get("/lecturers/{lecturer_id}/sessions/{session_id}/suggestions", response_model=List[dict])
    async def get_suggestions(
        lecturer_id: str,
        session_id: str,
        request: Request,
        date_: str = Query(..., alias="date"),
        time: str = Query(...),
        flex_days: int = Query(1, ge=0, le=7),
        limit: int = Query(6, ge=1, le=20),
        session: SessionUser = Depends(LECTURER_OR_ADMIN),
    ):
        """Free times close to the date and time the lecturer asked for (see suggest_slots)."""
        check_own_lecturer(session, lecturer_id)
        try:
            wanted_day = date.fromisoformat(date_)
            wanted_min = int(time[:2]) * 60 + int(time[3:5])
            if len(time) != 5 or time[2] != ":" or not 0 <= wanted_min < 24 * 60:
                raise ValueError
        except ValueError:
            raise HTTPException(422, {"message": "Choose a valid date and time.", "conflicts": []})
        db = database(request)
        try:
            moving = await get_own_session(db, lecturer_id, session_id)
            return await suggest_slots(db, moving, wanted_day, wanted_min, flex_days, limit)
        except Exception as exc:
            raise safe_database_error(exc) from exc

    @router.patch("/lecturers/{lecturer_id}/sessions/{session_id}")
    async def reschedule_session(lecturer_id: str, session_id: str, payload: RescheduleRequest, request: Request,
                                 session: SessionUser = Depends(LECTURER_OR_ADMIN)):
        check_own_lecturer(session, lecturer_id)
        try:
            new_start = datetime.combine(date.fromisoformat(payload.session_date),
                                         datetime.strptime(payload.start_time, "%H:%M").time(), tzinfo=MY_TZ)
        except ValueError:
            raise refuse(422, "Choose a valid date and time.")
        db = database(request)
        try:
            moving = await get_own_session(db, lecturer_id, session_id)  # exists, is theirs, not cancelled
            now = datetime.now(timezone.utc)
            current_start = parse_ts(moving["starts_at"])
            if current_start <= now:
                raise refuse(409, "Classes that have already started cannot be rescheduled.")
            if new_start <= now:
                raise refuse(409, "Choose a start time in the future.")
            if new_start == current_start and str(moving.get("room_id")) == payload.room_id:
                raise refuse(422, "Nothing has changed. Pick a different time or room.")

            # Check with the scheduling engine (the same rules as generated timetables).
            students = await load_roster(db, moving)
            snapshot = await load_target_snapshot(db, settings.scheduling, moving, students,
                                                  new_start.astimezone(MY_TZ).date())
        except Exception as exc:
            raise safe_database_error(exc) from exc
        room = next((r for r in snapshot.rooms if str(r.id) == payload.room_id), None)
        if room is None:
            raise refuse(422, "That room is not available.")
        time_issues, room_issues, _ = explain(BookingValidator(snapshot), UUID(str(moving["id"])),
                                              new_start.astimezone(timezone.utc), [room])
        problems = time_issues + room_issues.get(str(room.id), [])
        clashes = [{"type": CLASH_TYPES[p.code], "message": p.detail} for p in problems if p.code in CLASH_TYPES]
        if clashes:
            raise refuse(409, "That slot clashes with another booking.", clashes)
        if problems:  # opening hours, closed date, room type/capacity/auditorium rule, past time
            raise refuse(422, " ".join(p.detail for p in problems))

        # Move and record it in one database transaction, as the logged-in user (auth.uid()).
        token = getattr(request.state, "access_token", None)
        if not token:
            raise refuse(401, "Log in again to reschedule classes.")
        function = "admin_reschedule_class" if session.role == "admin" else "lecturer_reschedule_class"
        reason = (payload.reason or "").strip()[:500] or NO_REASON_TEXT
        try:
            await run_move_function(db, token, function, {
                "session_id": str(moving["id"]), "expected_start": current_start.isoformat(),
                "expected_room": str(moving["room_id"]) if moving.get("room_id") else None,
                "new_start": new_start.isoformat(),
                "new_room": str(room.id), "change_reason": reason,
            }, forbidden="You can only change your own classes.", migrations="202611120003, 202611120004")
        except MoveFailed as exc:
            raise refuse(exc.status, exc.message) from exc
        return {"status": "ok"}

    return router
