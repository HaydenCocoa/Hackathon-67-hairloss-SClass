"""Read and validate a complete week's engine input without creating bookings."""

import hashlib
import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, ValidationError, computed_field, field_validator, model_validator

from ..config import CourseType, RoomType, SchedulingSettings
from ..student import Supabase, in_list
from ..observability import event
from .calendar import TeachingCalendar
from .requirements import ACTIVE_BOOKING_STATUSES, ActiveBookingStatus, TeachingOccurrence


class SchedulingDataError(ValueError):
    """Safe, structured input error; never includes raw provider data."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(detail)


def _utc(value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise ValueError("Scheduling timestamps must include a timezone offset")
    return value.astimezone(timezone.utc)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RoomInput(_Frozen):
    id: UUID
    name: str = Field(min_length=1)
    building: str = Field(min_length=1)
    capacity: int = Field(gt=0, strict=True)
    room_type: Literal["classroom", "lab", "auditorium"]
    is_active: bool = Field(strict=True)


class LecturerInput(_Frozen):
    id: UUID


class RoomRule(_Frozen):
    course_type: CourseType
    allowed_room_types: frozenset[RoomType]


class _Roster(_Frozen):
    section_id: UUID
    intake_id: UUID
    group_number: int = Field(gt=0, strict=True)
    student_ids: frozenset[UUID]


class _Occurrence(TeachingOccurrence):
    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("starts_at")
    @classmethod
    def aware_start(cls, value: datetime | None) -> datetime | None:
        return _utc(value) if value is not None else None


class ClassRequirement(_Occurrence):
    student_ids: frozenset[UUID]

    @computed_field
    @property
    def student_count(self) -> int:
        return len(self.student_ids)


class _Interval(_Frozen):
    starts_at: datetime
    ends_at: datetime

    @field_validator("starts_at", "ends_at")
    @classmethod
    def aware_times(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def positive_interval(self) -> "_Interval":
        if self.ends_at <= self.starts_at:
            raise ValueError("Booking must have positive duration")
        return self


class OpeningWindow(_Interval):
    day: date


class _ClassRow(_Interval):
    id: UUID
    occurrence_id: UUID | None
    section_id: UUID
    intake_id: UUID
    group_number: int = Field(gt=0, strict=True)
    lecturer_id: UUID
    room_id: UUID
    duration_minutes: int = Field(gt=0, strict=True)
    status: ActiveBookingStatus

    @model_validator(mode="after")
    def derived_duration(self) -> "_ClassRow":
        if self.ends_at - self.starts_at != timedelta(minutes=self.duration_minutes):
            raise ValueError("Class end must match course duration")
        return self


class ClassBooking(_ClassRow):
    student_ids: frozenset[UUID]


class MeetingBooking(_Interval):
    id: UUID
    lecturer_id: UUID
    room_id: UUID | None
    status: Literal["scheduled"]
    student_ids: frozenset[UUID]


class _Payload(_Frozen):
    schema_version: Literal[1]
    week_start: date
    timezone: str
    horizon_starts_at: datetime
    horizon_ends_at: datetime
    captured_at: datetime
    database_snapshot: str = Field(min_length=1)
    requirements: tuple[_Occurrence, ...]
    rosters: tuple[_Roster, ...]
    rooms: tuple[RoomInput, ...]
    lecturers: tuple[LecturerInput, ...]
    class_bookings: tuple[_ClassRow, ...]
    meeting_bookings: tuple[MeetingBooking, ...]

    @field_validator("horizon_starts_at", "horizon_ends_at", "captured_at")
    @classmethod
    def aware_metadata(cls, value: datetime) -> datetime:
        return _utc(value)


class SchedulingSnapshot(_Frozen):
    week_start: date
    timezone: str
    horizon_starts_at: datetime
    horizon_ends_at: datetime
    captured_at: datetime
    database_snapshot: str
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    opening_windows: tuple[OpeningWindow, ...]
    requirements: tuple[ClassRequirement, ...]
    rooms: tuple[RoomInput, ...]
    lecturers: tuple[LecturerInput, ...]
    class_bookings: tuple[ClassBooking, ...]
    meeting_bookings: tuple[MeetingBooking, ...]
    room_rules: tuple[RoomRule, ...] = ()
    # Captured compulsory policy (part of the revision). Defaults keep hand-built test snapshots unchanged.
    min_gap_minutes: int = Field(default=0, ge=0, strict=True)
    reserved_room_types: frozenset[RoomType] = frozenset()

    @property
    def pending_requirements(self) -> tuple[ClassRequirement, ...]:
        return tuple(item for item in self.requirements if item.needs_scheduling)


def _unique(rows: tuple, key: str) -> dict:
    indexed = {getattr(item, key): item for item in rows}
    if len(indexed) != len(rows):
        raise SchedulingDataError("DUPLICATE_IDENTITY", "The database snapshot contains duplicate identities.")
    return indexed


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in value.items()}
    if isinstance(value, list):
        return sorted((_canonical(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True))
    return value


async def load_scheduling_snapshot(
    db: Supabase, settings: SchedulingSettings, week_start: date,
) -> SchedulingSnapshot:
    """Fetch source rows through Supabase's table/view API and resolve engine inputs.

    The backend owns query orchestration and snapshot assembly. PostgREST requests
    are separate reads rather than one PostgreSQL transaction, so the result is
    an observed capture, not a database-level point-in-time snapshot or lock.
    """
    if not isinstance(week_start, date) or isinstance(week_start, datetime) or week_start.weekday() != 0:
        raise ValueError("week_start must be a Monday date")
    # Isolate this load from accidental changes to the caller's mutable settings.
    settings = settings.model_copy(deep=True)
    zone = ZoneInfo(settings.timezone)
    start = datetime.combine(week_start, datetime.min.time(), zone).astimezone(timezone.utc)
    end = datetime.combine(week_start + timedelta(days=7), datetime.min.time(), zone).astimezone(timezone.utc)
    start_iso, end_iso = start.isoformat(), end.isoformat()

    async def fetch_all(stage: str, table: str, params: list[tuple[str, str]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        event("snapshot_query_started", stage=stage)
        try:
            while True:
                page = await db.get(table, [*params, ("limit", "500"), ("offset", str(len(rows)))])
                rows.extend(page)
                if len(page) < 500:
                    break
        except Exception as exc:
            event("snapshot_query_failed", level=logging.WARNING, stage=stage,
                  provider_status=getattr(exc, "provider_status", None), exception_type=type(exc).__name__)
            raise
        event("snapshot_query_completed", stage=stage, row_count=len(rows))
        return rows

    requirement_select = (
        "occurrence_id,plan_id,section_id,original_week_start,target_week_start,teaching_week_number,"
        "occurrence_number,requirement_status,timezone,class_session_id,booking_status,starts_at,room_id,"
        "needs_scheduling,group_number,intake_id,lecturer_id,course_id,course_code,course_name,course_type,duration_minutes"
    )
    requirements = await fetch_all("load_requirements", "teaching_occurrence_details", [
        ("select", requirement_select), ("target_week_start", f"eq.{week_start.isoformat()}"),
        ("order", "occurrence_id.asc"),
    ])
    class_rows = await fetch_all("load_class_bookings", "class_session_details", [
        ("select", "id,section_id,room_id,starts_at,ends_at,status,group_number,intake_id,lecturer_id,duration_minutes"),
        ("status", in_list(ACTIVE_BOOKING_STATUSES)), ("starts_at", f"lt.{end_iso}"), ("ends_at", f"gt.{start_iso}"),
        ("order", "id.asc"),
    ])
    if class_rows:
        links = await fetch_all("load_occurrence_links", "class_sessions", [
            ("select", "id,occurrence_id"), ("id", in_list(row["id"] for row in class_rows)),
            ("order", "id.asc"),
        ])
        occurrence_by_session = {row["id"]: row.get("occurrence_id") for row in links}
        for row in class_rows:
            row["occurrence_id"] = occurrence_by_session.get(row["id"])

    meetings = await fetch_all("load_meetings", "meeting_sessions", [
        ("select", "id,lecturer_id,room_id,starts_at,ends_at,status"), ("status", "eq.scheduled"),
        ("starts_at", f"lt.{end_iso}"), ("ends_at", f"gt.{start_iso}"), ("order", "id.asc"),
    ])
    if meetings:
        attendees = await fetch_all("load_meeting_attendees", "meeting_students", [
            ("select", "meeting_id,student_id"), ("meeting_id", in_list(row["id"] for row in meetings)),
            ("order", "meeting_id.asc,student_id.asc"),
        ])
        students_by_meeting: dict[str, list[str]] = {}
        for row in attendees:
            students_by_meeting.setdefault(row["meeting_id"], []).append(row["student_id"])
        for row in meetings:
            row["student_ids"] = students_by_meeting.get(row["id"], [])

    relevant_sections = {
        (row["section_id"], row["intake_id"], row["group_number"])
        for row in [*requirements, *class_rows]
    }
    intake_ids = {intake_id for _, intake_id, _ in relevant_sections}
    memberships = await fetch_all("load_group_memberships", "student_intakes", [
        ("select", "student_id,intake_id,group_number"), ("intake_id", in_list(intake_ids)),
        ("order", "intake_id.asc,group_number.asc,student_id.asc"),
    ]) if intake_ids else []
    students_by_group: dict[tuple[str, int], list[str]] = {}
    for row in memberships:
        students_by_group.setdefault((row["intake_id"], row["group_number"]), []).append(row["student_id"])
    rosters = [{
        "section_id": section_id, "intake_id": intake_id, "group_number": group_number,
        "student_ids": students_by_group.get((intake_id, group_number), []),
    } for section_id, intake_id, group_number in sorted(relevant_sections)]

    rooms = await fetch_all("load_rooms", "rooms", [
        ("select", "id,name,building,capacity,room_type,is_active"), ("order", "id.asc"),
    ])
    lecturer_ids = {row["lecturer_id"] for row in [*requirements, *class_rows, *meetings]}
    lecturers = await fetch_all("load_lecturers", "lecturers", [
        ("select", "id"), ("id", in_list(lecturer_ids)), ("order", "id.asc"),
    ]) if lecturer_ids else []

    captured_at = datetime.now(timezone.utc)
    raw = {
        "schema_version": 1, "week_start": week_start, "timezone": settings.timezone,
        "horizon_starts_at": start, "horizon_ends_at": end, "captured_at": captured_at,
        # This is a capture marker, not a PostgreSQL MVCC snapshot identifier.
        "database_snapshot": f"postgrest-multi-read:{captured_at.isoformat()}",
        "requirements": requirements, "rosters": rosters, "rooms": rooms,
        "lecturers": lecturers, "class_bookings": class_rows, "meeting_bookings": meetings,
    }
    try:
        data = _Payload.model_validate(raw)
    except ValidationError as exc:
        raise SchedulingDataError("INVALID_SNAPSHOT", "The database snapshot contains missing or invalid scheduling data.") from exc
    if (data.week_start, data.timezone, data.horizon_starts_at, data.horizon_ends_at) != (week_start, settings.timezone, start, end):
        raise SchedulingDataError("WRONG_HORIZON", "The database snapshot does not match the requested teaching week.")

    occurrences = _unique(data.requirements, "occurrence_id")
    rosters = _unique(data.rosters, "section_id")
    rooms = _unique(data.rooms, "id")
    lecturers = _unique(data.lecturers, "id")
    classes = _unique(data.class_bookings, "id")
    _unique(data.meeting_bookings, "id")
    linked = [item.occurrence_id for item in data.class_bookings if item.occurrence_id is not None]
    if len(set(linked)) != len(linked):
        raise SchedulingDataError("DUPLICATE_IDENTITY", "A teaching occurrence has multiple scheduled bookings.")

    def roster_for(section_id: UUID, intake_id: UUID, group_number: int) -> frozenset[UUID]:
        roster = rosters.get(section_id)
        if roster is None:
            raise SchedulingDataError("MISSING_ROSTER", "A class section has no roster entry in the database snapshot.")
        if (roster.intake_id, roster.group_number) != (intake_id, group_number):
            raise SchedulingDataError("ROSTER_MISMATCH", "A class roster does not match its intake and group.")
        return roster.student_ids

    def resource_refs(lecturer_id: UUID, room_id: UUID | None) -> None:
        if lecturer_id not in lecturers:
            raise SchedulingDataError("MISSING_LECTURER", "An assigned lecturer is missing from the database snapshot.")
        if room_id is not None and room_id not in rooms:
            raise SchedulingDataError("MISSING_ROOM", "A booked room is missing from the database snapshot.")

    def overlaps(booking: _Interval) -> None:
        if not (booking.starts_at < end and booking.ends_at > start):
            raise SchedulingDataError("OUTSIDE_HORIZON", "A returned booking does not overlap the selected week.")

    class_inputs = []
    for item in sorted(data.class_bookings, key=lambda item: str(item.id)):
        resource_refs(item.lecturer_id, item.room_id)
        overlaps(item)
        students = roster_for(item.section_id, item.intake_id, item.group_number)
        class_inputs.append(ClassBooking(**item.model_dump(), student_ids=students))
        if item.occurrence_id in occurrences and occurrences[item.occurrence_id].class_session_id != item.id:
            raise SchedulingDataError("BOOKING_MISMATCH", "A class booking disagrees with its teaching occurrence.")
    for item in data.meeting_bookings:
        resource_refs(item.lecturer_id, item.room_id)
        overlaps(item)

    requirement_inputs = []
    for item in sorted(data.requirements, key=lambda item: str(item.occurrence_id)):
        if item.target_week_start != week_start or item.original_week_start.weekday() != 0:
            raise SchedulingDataError("WRONG_HORIZON", "A teaching occurrence has an invalid source or target week.")
        if item.timezone != settings.timezone:
            raise SchedulingDataError("TIMEZONE_MISMATCH", "A teaching plan's timezone differs from the scheduling calendar.")
        resource_refs(item.lecturer_id, item.room_id)
        students = roster_for(item.section_id, item.intake_id, item.group_number)
        expected_pending = item.requirement_status == "required" and item.booking_status not in ACTIVE_BOOKING_STATUSES
        if item.needs_scheduling != expected_pending:
            raise SchedulingDataError("STATE_MISMATCH", "A teaching occurrence has inconsistent scheduling state.")
        if item.class_session_id is None:
            if any(value is not None for value in (item.booking_status, item.starts_at, item.room_id)):
                raise SchedulingDataError("STATE_MISMATCH", "An unbooked occurrence contains booking fields.")
        elif item.booking_status is None or item.starts_at is None:
            raise SchedulingDataError("STATE_MISMATCH", "A linked occurrence is missing its booking state.")
        if item.booking_status in ACTIVE_BOOKING_STATUSES:
            booking = classes.get(item.class_session_id)
            if (booking is None or item.requirement_status != "required" or
                (booking.occurrence_id, booking.section_id, booking.lecturer_id, booking.room_id,
                 booking.starts_at, booking.duration_minutes) !=
                (item.occurrence_id, item.section_id, item.lecturer_id, item.room_id, item.starts_at, item.duration_minutes)):
                raise SchedulingDataError("BOOKING_MISMATCH", "A scheduled requirement is missing its matching fixed booking.")
        if item.needs_scheduling and not students:
            raise SchedulingDataError("EMPTY_ROSTER", "A class needing placement has no enrolled students.")
        requirement_inputs.append(ClassRequirement(**item.model_dump(), student_ids=students))
    if any(item.needs_scheduling for item in requirement_inputs) and not rooms:
        raise SchedulingDataError("MISSING_ROOMS", "Room inventory is missing for the selected week's teaching requirements.")

    calendar = TeachingCalendar(settings)
    windows = []
    for offset in range(7):
        day = week_start + timedelta(days=offset)
        window = calendar.opening_window(day)
        if window is not None:
            windows.append(OpeningWindow(day=day, starts_at=window[0], ends_at=window[1]))
    snapshot = SchedulingSnapshot(
        week_start=week_start, timezone=settings.timezone, horizon_starts_at=start, horizon_ends_at=end,
        captured_at=data.captured_at, database_snapshot=data.database_snapshot, revision="0" * 64,
        opening_windows=tuple(windows), requirements=tuple(requirement_inputs),
        rooms=tuple(sorted(data.rooms, key=lambda item: str(item.id))),
        lecturers=tuple(sorted(data.lecturers, key=lambda item: str(item.id))),
        class_bookings=tuple(class_inputs), meeting_bookings=tuple(sorted(data.meeting_bookings, key=lambda item: str(item.id))),
        room_rules=tuple(RoomRule(course_type=kind, allowed_room_types=frozenset(allowed))
                         for kind, allowed in sorted(settings.room_compatibility.items())),
        min_gap_minutes=settings.min_gap_minutes, reserved_room_types=frozenset(settings.reserved_room_types),
    )
    content = snapshot.model_dump(mode="json", exclude={"revision", "captured_at", "database_snapshot"})
    revision = hashlib.sha256(json.dumps(_canonical(content), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return snapshot.model_copy(update={"revision": revision})
