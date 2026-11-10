"""Read and validate a complete week's engine input without creating bookings."""

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, ValidationError, computed_field, field_validator, model_validator

from ..config import CourseType, RoomType, SchedulingSettings
from ..student import Supabase
from .calendar import TeachingCalendar
from .requirements import TeachingOccurrence


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
    status: Literal["scheduled"]

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
    """Use one STABLE database RPC, then resolve immutable engine inputs.

    The result is a point-in-time read, not a resource lock or committed booking.
    This function is internal and requires a trusted server database reader.
    """
    if not isinstance(week_start, date) or isinstance(week_start, datetime) or week_start.weekday() != 0:
        raise ValueError("week_start must be a Monday date")
    # Isolate this load from accidental changes to the caller's mutable settings.
    settings = settings.model_copy(deep=True)
    zone = ZoneInfo(settings.timezone)
    start = datetime.combine(week_start, datetime.min.time(), zone).astimezone(timezone.utc)
    end = datetime.combine(week_start + timedelta(days=7), datetime.min.time(), zone).astimezone(timezone.utc)
    raw = await db.rpc("load_scheduling_data", {"p_week_start": week_start.isoformat(), "p_timezone": settings.timezone})
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
        expected_pending = item.requirement_status == "required" and item.booking_status != "scheduled"
        if item.needs_scheduling != expected_pending:
            raise SchedulingDataError("STATE_MISMATCH", "A teaching occurrence has inconsistent scheduling state.")
        if item.class_session_id is None:
            if any(value is not None for value in (item.booking_status, item.starts_at, item.room_id)):
                raise SchedulingDataError("STATE_MISMATCH", "An unbooked occurrence contains booking fields.")
        elif item.booking_status is None or item.starts_at is None:
            raise SchedulingDataError("STATE_MISMATCH", "A linked occurrence is missing its booking state.")
        if item.booking_status == "scheduled":
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
    )
    content = snapshot.model_dump(mode="json", exclude={"revision", "captured_at", "database_snapshot"})
    revision = hashlib.sha256(json.dumps(_canonical(content), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return snapshot.model_copy(update={"revision": revision})
