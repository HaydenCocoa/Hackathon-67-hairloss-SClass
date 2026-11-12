"""Step 8: measure a generated timetable, independently of the solver.

The solver's objective steers the search; these measurements report the
result. They are computed from the final placements plus the fixed bookings
already in the snapshot, so they stay true even when the search stopped early.
Only counts and minutes are returned: no ids, names or rosters.
"""

from collections import defaultdict
from datetime import date, datetime
from typing import Iterable
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from .loader import SchedulingSnapshot
from .requirements import ACTIVE_BOOKING_STATUSES


class QualityReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    student_days: int = Field(ge=0, description="Student-days that contain at least one new class")
    student_idle_minutes_total: int = Field(ge=0, description="Waiting time between each student's first and last class, summed over those days")
    student_idle_minutes_average: float = Field(ge=0, description="Average idle minutes per student-day")
    student_idle_minutes_max: int = Field(ge=0, description="Worst single student-day")
    longest_student_day_minutes: int = Field(ge=0, description="Longest first-class-to-last-class span of any student-day")
    lecturer_days: int = Field(ge=0)
    lecturer_idle_minutes_total: int = Field(ge=0)
    lecturer_idle_minutes_max: int = Field(ge=0)
    empty_seats_total: int = Field(ge=0, description="Room capacity minus students, summed over the new classes")
    seat_use_percent: float = Field(ge=0, le=100, description="Students / seats over the new classes")
    reserved_room_classes: int = Field(ge=0, description="New classes placed in a reserved room type (auditorium)")


Interval = tuple[datetime, datetime]


def _day_stats(intervals: list[Interval]) -> tuple[int, int]:
    """(span minutes, idle minutes) for one person's day; overlapping intervals are merged."""
    ordered = sorted(intervals)
    busy, cursor_start, cursor_end = 0.0, *ordered[0]
    for start, end in ordered[1:]:
        if start <= cursor_end:
            cursor_end = max(cursor_end, end)
        else:
            busy += (cursor_end - cursor_start).total_seconds()
            cursor_start, cursor_end = start, end
    busy += (cursor_end - cursor_start).total_seconds()
    span = (max(end for _, end in ordered) - ordered[0][0]).total_seconds()
    return round(span / 60), round((span - busy) / 60)


def _people_days(new: dict[UUID, list[Interval]], fixed: dict[UUID, list[Interval]], zone: ZoneInfo
                 ) -> Iterable[tuple[int, int]]:
    """Yield (span, idle) for each person-day that contains a new class."""
    for person, classes in new.items():
        by_day: dict[date, list[Interval]] = defaultdict(list)
        for start, end in classes:
            by_day[start.astimezone(zone).date()].append((start, end))
        for start, end in fixed.get(person, ()):
            day = start.astimezone(zone).date()
            if day in by_day:
                by_day[day].append((start, end))
        for intervals in by_day.values():
            yield _day_stats(intervals)


def measure_quality(snapshot: SchedulingSnapshot, placements) -> QualityReport:
    zone = ZoneInfo(snapshot.timezone)
    pending = {item.occurrence_id: item for item in snapshot.pending_requirements}
    rooms = {item.id: item for item in snapshot.rooms}

    student_new: dict[UUID, list[Interval]] = defaultdict(list)
    lecturer_new: dict[UUID, list[Interval]] = defaultdict(list)
    seats = students = reserved = 0
    for item in placements:
        lesson, room = pending[item.occurrence_id], rooms[item.room_id]
        for student_id in lesson.student_ids:
            student_new[student_id].append((item.starts_at, item.ends_at))
        lecturer_new[item.lecturer_id].append((item.starts_at, item.ends_at))
        seats += room.capacity
        students += lesson.student_count
        reserved += room.room_type in snapshot.reserved_room_types

    student_fixed: dict[UUID, list[Interval]] = defaultdict(list)
    lecturer_fixed: dict[UUID, list[Interval]] = defaultdict(list)
    fixed = [*(b for b in snapshot.class_bookings if b.status in ACTIVE_BOOKING_STATUSES),
             *(m for m in snapshot.meeting_bookings if m.status == "scheduled")]
    for booking in fixed:
        for student_id in booking.student_ids & student_new.keys():
            student_fixed[student_id].append((booking.starts_at, booking.ends_at))
        if booking.lecturer_id in lecturer_new:
            lecturer_fixed[booking.lecturer_id].append((booking.starts_at, booking.ends_at))

    student_stats = list(_people_days(student_new, student_fixed, zone))
    lecturer_stats = list(_people_days(lecturer_new, lecturer_fixed, zone))
    student_idle = sum(idle for _, idle in student_stats)
    return QualityReport(
        student_days=len(student_stats), student_idle_minutes_total=student_idle,
        student_idle_minutes_average=round(student_idle / len(student_stats), 1) if student_stats else 0.0,
        student_idle_minutes_max=max((idle for _, idle in student_stats), default=0),
        longest_student_day_minutes=max((span for span, _ in student_stats), default=0),
        lecturer_days=len(lecturer_stats), lecturer_idle_minutes_total=sum(idle for _, idle in lecturer_stats),
        lecturer_idle_minutes_max=max((idle for _, idle in lecturer_stats), default=0),
        empty_seats_total=seats - students, seat_use_percent=round(100 * students / seats, 1) if seats else 0.0,
        reserved_room_classes=reserved,
    )
