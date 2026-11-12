"""Admin rescheduling of one existing class: room/time availability and the move itself.

Both endpoints reuse the scheduling engine, so a move follows exactly the same compulsory rules as
generated timetables: opening hours and closed dates, whole-minute starts, room type, capacity and the
auditorium rule, the gap between bookings, and no clash for the room, the lecturer or any student
(classes and meetings, across all intakes).

How: load the TARGET week's snapshot, remove the class's own current booking from it, and add the class
as the only class to place (`moving_snapshot`). `BookingValidator` then explains each room at one start
time, and `CandidateGenerator` gives every free start per room for the day's time grid. This also works
for classes without a teaching occurrence and for moves into another week.

Saving re-checks the move against fresh data, then calls the database function
`public.admin_reschedule_class` (migrations 202611110001 + 202611120003), which takes the timetable lock,
re-checks clashes, marks the class `rescheduled` and writes the audit row in one transaction.
See docs/backend/admin-reschedule-api.md.
"""

import logging
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..auth import SessionUser, get_session
from ..config import Settings
from ..observability import REQUEST_ID, event, safe_frames
from ..student import Supabase
from .candidates import CandidateGenerator
from .loader import ClassRequirement, SchedulingDataError, SchedulingSnapshot, load_scheduling_snapshot
from .preview import failure, origin_allowed
from .requirements import ACTIVE_BOOKING_STATUSES
from .validator import BookingProposal, BookingValidator

# Start times offered in the dialog's time grid (any whole minute is still accepted by the API).
SLOT_MINUTES = 15
# The database function needs a non-empty reason; an optional one left blank is recorded as this text.
NO_REASON_TEXT = "No reason given"
# Issues about one room; every other issue makes the time itself unavailable, whatever the room.
ROOM_CODES = {"ROOM_NOT_FOUND", "ROOM_INACTIVE", "ROOM_TOO_SMALL", "ROOM_POLICY_UNDEFINED", "ROOM_TYPE_MISMATCH",
              "ROOM_RESERVED_FOR_LARGE_CLASSES", "ROOM_CONFLICT"}
CLASS_SELECT = ("id,section_id,room_id,starts_at,ends_at,status,group_number,intake_id,lecturer_id,course_id,"
                "course_code,course_name,course_type,duration_minutes")
NIL = UUID(int=0)


class Issue(BaseModel):
    code: str
    detail: str


class RoomOption(BaseModel):
    id: UUID
    name: str
    building: str
    room_type: str
    capacity: int
    is_active: bool
    suitable: bool = Field(description="False when the room can never take this class (inactive, too small, wrong type)")
    issues: list[Issue] = Field(description="Why the room is never suitable; empty when suitable")


class Slot(BaseModel):
    start: str = Field(description="Campus-local start time, HH:MM")
    end: str
    starts_at: datetime
    free_room_ids: list[UUID] = Field(description="Rooms in which the whole class fits at this start; empty if none")


class SelectedTime(BaseModel):
    start: str
    end: str
    starts_at: datetime
    ends_at: datetime
    time_issues: list[Issue] = Field(description="Problems with the time itself (any room): opening hours, past, lecturer or students busy")
    available_room_ids: list[UUID]
    room_issues: dict[str, list[Issue]] = Field(description="For each unavailable room id, why")


class Availability(BaseModel):
    session_id: UUID
    date: date
    timezone: str
    duration_minutes: int
    student_count: int = Field(description="Students in the class (its intake and group), the seats a room needs")
    status: str = Field(description="The class's booking status: scheduled or rescheduled (moved before)")
    step_minutes: int
    rooms: list[RoomOption]
    slots: list[Slot] = Field(description="Start times on `date` within opening hours, every step_minutes, plus the class's current start")
    selected: SelectedTime | None = Field(description="Details for `start`, when it was given")


class RescheduleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_starts_at: datetime = Field(description="The class's start as the page loaded it (detects changes made meanwhile)")
    expected_room_id: UUID = Field(description="The class's room as the page loaded it")
    starts_at: datetime = Field(description="New start, with a timezone offset; whole minutes")
    room_id: UUID = Field(description="New room")
    reason: str | None = Field(default=None, max_length=500,
                               description="Optional: why the class moves (kept in the change history). When it is "
                                           "missing or blank, the history records NO_REASON_TEXT instead.")

    @field_validator("reason")
    @classmethod
    def blank_is_none(cls, value: str | None) -> str | None:
        return value or None

    @field_validator("expected_starts_at", "starts_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("Times must include a timezone offset")
        return value.astimezone(timezone.utc)


class RescheduleResult(BaseModel):
    status: Literal["RESCHEDULED"] = "RESCHEDULED"
    session_id: UUID
    starts_at: datetime
    ends_at: datetime
    room_id: UUID


def _ts(value: str) -> datetime:
    text = value.replace(" ", "T").replace("Z", "+00:00")
    if re.search(r"[+-]\d{2}$", text):
        text += ":00"
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def moving_snapshot(snapshot: SchedulingSnapshot, row: dict, student_ids: frozenset[UUID]) -> SchedulingSnapshot:
    """The target week with the class to move as its only class to place, and its current booking removed."""
    week = snapshot.week_start
    requirement = ClassRequirement(
        occurrence_id=UUID(str(row["id"])), plan_id=NIL, section_id=row["section_id"],
        original_week_start=week, target_week_start=week, teaching_week_number=1, occurrence_number=1,
        requirement_status="required", timezone=snapshot.timezone, class_session_id=None, booking_status=None,
        starts_at=None, room_id=None, needs_scheduling=True, group_number=row["group_number"],
        intake_id=row["intake_id"], lecturer_id=row["lecturer_id"], course_id=row["course_id"],
        course_code=row["course_code"], course_name=row["course_name"], course_type=row["course_type"],
        duration_minutes=row["duration_minutes"], student_ids=student_ids,
    )
    own = UUID(str(row["id"]))
    return snapshot.model_copy(update={
        "requirements": (requirement,),
        "class_bookings": tuple(item for item in snapshot.class_bookings if item.id != own),
    })


def create_reschedule_router(settings: Settings) -> APIRouter:
    zone = ZoneInfo(settings.scheduling.timezone)
    router = APIRouter(prefix="/api/admin/timetable", tags=["admin rescheduling"])

    async def admin(request: Request, session: SessionUser | None = Depends(get_session)) -> SessionUser:
        if session is None:
            raise failure(401, "AUTH_REQUIRED", "Log in as an administrator to reschedule classes.", "reschedule_rejected")
        if session.role != "admin":
            raise failure(403, "ADMIN_REQUIRED", "Only administrators can reschedule classes here.", "reschedule_rejected")
        return session

    async def same_site(request: Request):
        if not origin_allowed(request, settings.server.cors_origins):
            raise failure(403, "ORIGIN_NOT_ALLOWED", "This browser origin cannot reschedule classes.", "reschedule_rejected")

    async def load_class(db: Supabase, session_id: UUID) -> tuple[dict, frozenset[UUID]]:
        rows = await db.get("class_session_details", [("select", CLASS_SELECT), ("id", f"eq.{session_id}")])
        if not rows:
            raise failure(404, "CLASS_NOT_FOUND", "This class does not exist or was removed.", "reschedule_rejected")
        row = rows[0]
        if row.get("status") not in ACTIVE_BOOKING_STATUSES:
            raise failure(409, "CLASS_NOT_ACTIVE", "A cancelled class cannot be rescheduled.", "reschedule_rejected")
        if _ts(row["starts_at"]) <= datetime.now(timezone.utc):
            raise failure(409, "CLASS_STARTED", "This class has already started, so it can no longer be moved.",
                          "reschedule_rejected")
        students: list[str] = []
        while True:
            page = await db.get("student_intakes", [
                ("select", "student_id"), ("intake_id", f"eq.{row['intake_id']}"),
                ("group_number", f"eq.{row['group_number']}"), ("order", "student_id.asc"),
                ("limit", "1000"), ("offset", str(len(students))),
            ])
            students.extend(item["student_id"] for item in page)
            if len(page) < 1000:
                break
        return row, frozenset(UUID(str(item)) for item in students)

    async def target_snapshot(db: Supabase, row: dict, students: frozenset[UUID], day: date) -> SchedulingSnapshot:
        snapshot = await load_scheduling_snapshot(db, settings.scheduling, day - timedelta(days=day.weekday()))
        return moving_snapshot(snapshot, row, students)

    def explain(validator: BookingValidator, occurrence: UUID, starts_at: datetime, rooms) -> tuple[list[Issue], dict, list]:
        """Validate one start in every room: time-wide issues, per-room issues, and the free rooms."""
        time_issues: dict[str, Issue] = {}
        if starts_at <= datetime.now(timezone.utc):
            time_issues["IN_PAST"] = Issue(code="IN_PAST", detail="This time has already passed.")
        room_issues, free = {}, []
        for room in rooms:
            checked = validator.validate(BookingProposal(occurrence_id=occurrence, room_id=room.id, starts_at=starts_at))
            mine = [Issue(code=item.code, detail=item.detail) for item in checked.issues if item.code in ROOM_CODES]
            for item in checked.issues:
                if item.code not in ROOM_CODES:
                    time_issues.setdefault(item.code, Issue(code=item.code, detail=item.detail))
            if mine:
                room_issues[str(room.id)] = list({issue.code: issue for issue in mine}.values())
            elif not time_issues:
                free.append(room.id)
        return list(time_issues.values()), room_issues, ([] if time_issues else free)

    def local(moment: datetime) -> str:
        return moment.astimezone(zone).strftime("%H:%M")

    def database_error(exc: Exception) -> HTTPException:
        if isinstance(exc, SchedulingDataError):
            return failure(502, exc.code, exc.detail, "reschedule_rejected")
        if isinstance(exc, HTTPException) and not isinstance(exc.detail, dict):
            code = {503: "DATABASE_NOT_CONFIGURED", 504: "DATABASE_TIMEOUT"}.get(exc.status_code, "DATABASE_UNAVAILABLE")
            return failure(exc.status_code, code, str(exc.detail), "reschedule_rejected")
        if isinstance(exc, HTTPException):
            return exc
        event("reschedule_failed", level=logging.ERROR, exception_type=type(exc).__name__, frames=safe_frames(exc))
        return failure(500, "RESCHEDULE_FAILED", "Availability could not be checked because of an internal error.",
                       "reschedule_rejected")

    @router.get(
        "/{session_id}/availability", response_model=Availability,
        summary="Which rooms and start times are free for moving one class (admin)",
        description="For one day: every room with whether it can ever take the class, and a time grid of start "
                    f"times (every {SLOT_MINUTES} minutes in opening hours) with the rooms free at each. With `start`, "
                    "also explains that time: problems with the time itself, and why each unavailable room is "
                    "unavailable. Read-only; uses the same compulsory rules as timetable generation.",
    )
    async def availability(
        session_id: UUID, request: Request, response: Response,
        day: date = Query(alias="date", description="Campus date to check (YYYY-MM-DD)"),
        start: str | None = Query(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$", description="Campus start time HH:MM"),
        _admin: SessionUser = Depends(admin),
    ):
        response.headers["Cache-Control"] = "no-store"
        db = Supabase(settings.supabase, request.app.state.http_client)
        try:
            row, students = await load_class(db, session_id)
            snapshot = await target_snapshot(db, row, students, day)
        except Exception as exc:
            raise database_error(exc) from exc
        occurrence = UUID(str(row["id"]))
        validator = BookingValidator(snapshot)
        rooms = sorted(snapshot.rooms, key=lambda item: item.name)
        options = []
        for room in rooms:
            issues = [Issue(code=item.code, detail=item.detail) for item in validator.room_issues(occurrence, room.id)]
            options.append(RoomOption(id=room.id, name=room.name, building=room.building, room_type=room.room_type,
                                      capacity=room.capacity, is_active=room.is_active, suitable=not issues, issues=issues))

        duration = timedelta(minutes=row["duration_minutes"])
        ranges = CandidateGenerator(snapshot).generate(occurrence).ranges
        now = datetime.now(timezone.utc)
        current = _ts(row["starts_at"])
        starts: set[datetime] = set()
        for window in snapshot.opening_windows:
            if window.day != day:
                continue
            moment = window.starts_at
            while moment + duration <= window.ends_at:
                starts.add(moment)
                moment += timedelta(minutes=SLOT_MINUTES)
        if current.astimezone(zone).date() == day:
            starts.add(current)  # keep the class's own (possibly off-grid) time selectable
        slots = []
        for moment in sorted(starts):
            free = [] if moment <= now else sorted(
                {item.room_id for item in ranges if item.earliest_start <= moment <= item.latest_start}, key=str)
            slots.append(Slot(start=local(moment), end=local(moment + duration), starts_at=moment, free_room_ids=free))

        selected = None
        if start is not None:
            starts_at = datetime.combine(day, time.fromisoformat(start), zone).astimezone(timezone.utc)
            time_issues, room_issues, free = explain(validator, occurrence, starts_at, rooms)
            selected = SelectedTime(start=start, end=local(starts_at + duration), starts_at=starts_at,
                                    ends_at=starts_at + duration, time_issues=time_issues,
                                    available_room_ids=free, room_issues=room_issues)
        event("availability_checked", row_count=len(slots))
        return Availability(session_id=session_id, date=day, timezone=settings.scheduling.timezone,
                            duration_minutes=row["duration_minutes"], student_count=len(students),
                            status=row["status"], step_minutes=SLOT_MINUTES, rooms=options,
                            slots=slots, selected=selected)

    @router.post(
        "/{session_id}/reschedule", response_model=RescheduleResult,
        summary="Move one class to a new room and start (admin)",
        description="Re-checks the move against fresh data with the scheduling engine (all compulsory rules), then "
                    "calls public.admin_reschedule_class, which locks the timetable, re-checks clashes, marks the "
                    "class rescheduled and records the change, all in one transaction. Visible to everyone at once.",
    )
    async def reschedule(session_id: UUID, body: RescheduleRequest, request: Request, response: Response,
                         _origin: None = Depends(same_site), _admin: SessionUser = Depends(admin)):
        response.headers["Cache-Control"] = "no-store"
        if body.starts_at.second or body.starts_at.microsecond:
            raise failure(422, "START_NOT_WHOLE_MINUTE", "Classes start on a whole minute.", "reschedule_rejected")
        db = Supabase(settings.supabase, request.app.state.http_client)
        try:
            row, students = await load_class(db, session_id)
            if _ts(row["starts_at"]) != body.expected_starts_at or str(row["room_id"]) != str(body.expected_room_id):
                raise failure(409, "CLASS_CHANGED", "This class was changed by someone else since you opened it. "
                              "Reload and try again.", "reschedule_rejected")
            if (_ts(row["starts_at"]), str(row["room_id"])) == (body.starts_at, str(body.room_id)):
                raise failure(422, "NO_CHANGE", "Choose a different time or room.", "reschedule_rejected")
            snapshot = await target_snapshot(db, row, students, body.starts_at.astimezone(zone).date())
        except Exception as exc:
            raise database_error(exc) from exc
        validator = BookingValidator(snapshot)
        room = next((item for item in snapshot.rooms if item.id == body.room_id), None)
        time_issues, room_issues, _ = explain(validator, UUID(str(row["id"])), body.starts_at, [room] if room else [])
        problems = time_issues + room_issues.get(str(body.room_id), [])
        if room is None:
            problems.append(Issue(code="ROOM_NOT_FOUND", detail="The room does not exist."))
        if problems:
            event("reschedule_rejected", level=logging.WARNING, http_status=409, code="SLOT_UNAVAILABLE")
            raise HTTPException(409, {"code": "SLOT_UNAVAILABLE", "message": "That room and time are not available: "
                                      + " ".join(issue.detail for issue in problems),
                                      "issues": [issue.model_dump() for issue in problems],
                                      "request_id": REQUEST_ID.get()}, headers={"Cache-Control": "no-store"})
        token = getattr(request.state, "access_token", None)
        if not token:
            raise failure(401, "AUTH_REQUIRED", "Log in again to reschedule classes.", "reschedule_rejected")
        try:
            reply = await db.client.post(
                f"{db.url}/rest/v1/rpc/admin_reschedule_class", headers={**db.headers, "Authorization": f"Bearer {token}"},
                json={"session_id": str(session_id), "expected_start": body.expected_starts_at.isoformat(),
                      "expected_room": str(body.expected_room_id), "new_start": body.starts_at.isoformat(),
                      "new_room": str(body.room_id), "change_reason": body.reason or NO_REASON_TEXT},
                timeout=db.timeout,
            )
        except httpx.TimeoutException as exc:
            raise failure(504, "RESCHEDULE_OUTCOME_UNKNOWN", "The database did not answer in time; the class may or may "
                          "not have moved. Reload the timetable before trying again.", "reschedule_rejected") from exc
        except httpx.RequestError as exc:
            raise failure(502, "DATABASE_UNAVAILABLE", "Could not reach the database. Nothing was changed.",
                          "reschedule_rejected") from exc
        if reply.status_code >= 400:
            try:
                code = reply.json().get("code")
            except ValueError:
                code = None
            known = {
                "23P01": (409, "SLOT_TAKEN", "Someone booked that room or time a moment ago. Nothing was changed; choose again."),
                "40001": (409, "CLASS_CHANGED", "This class was changed by someone else. Reload and try again."),
                "22023": (409, "MOVE_REJECTED", "The database refused this move (status, room suitability or capacity)."),
                "P0002": (404, "CLASS_NOT_FOUND", "This class does not exist or was removed."),
                "42501": (403, "ADMIN_REQUIRED", "The database did not accept your administrator account."),
                "PGRST202": (503, "MIGRATION_MISSING", "The admin timetable migrations (202611110001, 202611120003) are not applied."),
                "42883": (503, "MIGRATION_MISSING", "The admin timetable migrations (202611110001, 202611120003) are not applied."),
                "42703": (503, "MIGRATION_MISSING", "Apply migration 202611120003_admin_reschedule_fixes.sql."),
            }
            status, error, message = known.get(code, (502, "DATABASE_REJECTED", "The database could not move the class. Nothing was changed."))
            raise failure(status, error, message, "reschedule_rejected")
        event("reschedule_completed")
        return RescheduleResult(session_id=session_id, starts_at=body.starts_at,
                                ends_at=body.starts_at + timedelta(minutes=row["duration_minutes"]), room_id=body.room_id)

    return router
