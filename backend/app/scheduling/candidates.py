"""Complete feasible start ranges against fixed bookings, without a time grid."""

from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from .loader import SchedulingSnapshot
from .validator import BookingIssue, BookingValidator, IssueCode, ProposalMode

CandidateCode = IssueCode | Literal[
    "NO_ROOMS", "NO_TEACHING_WINDOWS", "DURATION_EXCEEDS_OPENING_WINDOWS",
    "NO_SUITABLE_ROOMS", "NO_VALID_START_RANGE",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CandidateRange(_Frozen):
    occurrence_id: UUID
    room_id: UUID
    earliest_start: datetime
    latest_start: datetime
    duration_minutes: int = Field(gt=0, strict=True)

    @field_validator("earliest_start", "latest_start")
    @classmethod
    def aware_times(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("Candidate boundaries must include timezone offsets")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def ordered(self) -> "CandidateRange":
        if self.latest_start < self.earliest_start:
            raise ValueError("latest_start must be at or after earliest_start")
        return self

    def contains(self, starts_at: datetime) -> bool:
        if starts_at.utcoffset() is None:
            raise ValueError("starts_at must include a timezone offset")
        return self.earliest_start <= starts_at.astimezone(timezone.utc) <= self.latest_start


class CandidateDiagnostic(_Frozen):
    code: CandidateCode
    detail: str
    room_id: UUID | None = None
    booking_id: UUID | None = None
    booking_kind: Literal["class", "meeting"] | None = None
    conflicting_student_count: int = Field(default=0, ge=0)


class OccurrenceCandidates(_Frozen):
    occurrence_id: UUID
    mode: ProposalMode
    snapshot_revision: str
    horizon_starts_at: datetime
    horizon_ends_at: datetime
    ranges: tuple[CandidateRange, ...]
    diagnostics: tuple[CandidateDiagnostic, ...]

    @computed_field
    @property
    def has_candidates(self) -> bool:
        return bool(self.ranges)


class WeeklyCandidates(_Frozen):
    snapshot_revision: str
    horizon_starts_at: datetime
    horizon_ends_at: datetime
    occurrences: tuple[OccurrenceCandidates, ...]

    @property
    def blocked_occurrence_ids(self) -> tuple[UUID, ...]:
        return tuple(item.occurrence_id for item in self.occurrences if not item.has_candidates)


class _Request(_Frozen):
    occurrence_id: UUID
    mode: ProposalMode


def _merged(intervals: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    result: list[tuple[datetime, datetime]] = []
    for start, end in sorted(intervals):
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(result[-1][1], end))
        else:
            result.append((start, end))
    return result


class CandidateGenerator:
    """Per-occurrence possibilities only; new lessons are not assigned together."""

    def __init__(self, snapshot: SchedulingSnapshot):
        self.snapshot = snapshot
        self._validator = BookingValidator(snapshot)

    def generate(self, occurrence_id: UUID, *, mode: ProposalMode = "schedule") -> OccurrenceCandidates:
        request = _Request(occurrence_id=occurrence_id, mode=mode)
        occurrence_id = request.occurrence_id
        diagnostics: list[CandidateDiagnostic] = []
        ranges: list[CandidateRange] = []

        def result() -> OccurrenceCandidates:
            unique = {}
            for item in diagnostics:
                unique.setdefault((item.code, item.room_id, item.booking_id, item.booking_kind), item)
            return OccurrenceCandidates(
                occurrence_id=occurrence_id, mode=mode, snapshot_revision=self.snapshot.revision,
                horizon_starts_at=self.snapshot.horizon_starts_at, horizon_ends_at=self.snapshot.horizon_ends_at,
                ranges=tuple(sorted(ranges, key=lambda item: (str(item.room_id), item.earliest_start, item.latest_start))),
                diagnostics=tuple(unique.values()),
            )

        def add_issue(item: BookingIssue, room_id: UUID | None = None) -> None:
            diagnostics.append(CandidateDiagnostic(**item.model_dump(), room_id=room_id))

        lifecycle = self._validator.occurrence_issues(occurrence_id, mode)
        if lifecycle:
            for item in lifecycle:
                add_issue(item)
            return result()
        requirement = self._validator.get_requirement(occurrence_id)
        assert requirement is not None  # checked by occurrence_issues
        try:
            duration = timedelta(minutes=requirement.duration_minutes)
        except OverflowError:
            diagnostics.append(CandidateDiagnostic(code="INVALID_START_TIME", detail="The course duration exceeds the supported date range."))
            return result()
        windows = sorted((max(window.starts_at, self.snapshot.horizon_starts_at),
                          min(window.ends_at, self.snapshot.horizon_ends_at)) for window in self.snapshot.opening_windows)
        windows = [(start, end) for start, end in windows if start < end]
        if not windows:
            diagnostics.append(CandidateDiagnostic(code="NO_TEACHING_WINDOWS", detail="No configured teaching window is open within this captured week."))
            return result()
        windows = [(start, end) for start, end in windows if end - start >= duration]
        if not windows:
            diagnostics.append(CandidateDiagnostic(code="DURATION_EXCEEDS_OPENING_WINDOWS", detail="The full class duration does not fit any opening window in this week."))
            return result()
        if not self.snapshot.rooms:
            diagnostics.append(CandidateDiagnostic(code="NO_ROOMS", detail="The scheduling snapshot contains no room inventory."))
            return result()

        suitable_count = 0
        for room in sorted(self.snapshot.rooms, key=lambda item: str(item.id)):
            room_issues = self._validator.room_issues(occurrence_id, room.id)
            if room_issues:
                for item in room_issues:
                    add_issue(item, room.id)
                continue
            suitable_count += 1
            blockers = self._validator.blocking_intervals(occurrence_id, room.id, mode)
            room_ranges = []
            for opens_at, closes_at in windows:
                occupied = _merged([(max(opens_at, item.starts_at), min(closes_at, item.ends_at))
                                    for item in blockers if item.starts_at < closes_at and item.ends_at > opens_at])
                cursor = opens_at
                gaps = []
                for busy_start, busy_end in occupied:
                    if busy_start - cursor >= duration:
                        gaps.append((cursor, busy_start - duration))
                    cursor = max(cursor, busy_end)
                if closes_at - cursor >= duration:
                    gaps.append((cursor, closes_at - duration))
                room_ranges.extend(CandidateRange(
                    occurrence_id=occurrence_id, room_id=room.id, earliest_start=start,
                    latest_start=end, duration_minutes=requirement.duration_minutes,
                ) for start, end in gaps)
            ranges.extend(room_ranges)
            if not room_ranges:
                # Supporting blockers, not a claimed minimum explanation of infeasibility.
                for item in sorted(blockers, key=lambda item: (item.starts_at, item.ends_at)):
                    if any(item.starts_at < end and item.ends_at > start for start, end in windows):
                        for reason in item.issues:
                            add_issue(reason, room.id)
        if not suitable_count:
            diagnostics.append(CandidateDiagnostic(code="NO_SUITABLE_ROOMS", detail="No room satisfies the captured activity, capacity, and teaching-type policy."))
        elif not ranges:
            diagnostics.append(CandidateDiagnostic(code="NO_VALID_START_RANGE", detail="Existing bookings leave no gap long enough in a suitable room during this captured week."))
        return result()

    def generate_pending(self) -> WeeklyCandidates:
        return WeeklyCandidates(
            snapshot_revision=self.snapshot.revision,
            horizon_starts_at=self.snapshot.horizon_starts_at, horizon_ends_at=self.snapshot.horizon_ends_at,
            occurrences=tuple(self.generate(item.occurrence_id) for item in sorted(
                self.snapshot.pending_requirements, key=lambda item: str(item.occurrence_id))),
        )


def generate_candidates(snapshot: SchedulingSnapshot, occurrence_id: UUID, *, mode: ProposalMode = "schedule") -> OccurrenceCandidates:
    return CandidateGenerator(snapshot).generate(occurrence_id, mode=mode)


def generate_weekly_candidates(snapshot: SchedulingSnapshot) -> WeeklyCandidates:
    return CandidateGenerator(snapshot).generate_pending()
