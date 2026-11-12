"""Explainable single-class validation against an immutable weekly snapshot."""

from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from .loader import ClassRequirement, SchedulingSnapshot
from .requirements import ACTIVE_BOOKING_STATUSES

ProposalMode = Literal["schedule", "reschedule"]

IssueCode = Literal[
    "OCCURRENCE_NOT_FOUND", "OCCURRENCE_CANCELLED", "ALREADY_SCHEDULED", "NOT_SCHEDULED",
    "ORIGINAL_BOOKING_NOT_FOUND", "INVALID_START_TIME", "OUTSIDE_HORIZON", "OUTSIDE_TEACHING_HOURS",
    "ROOM_NOT_FOUND", "ROOM_INACTIVE", "ROOM_TOO_SMALL", "ROOM_POLICY_UNDEFINED", "ROOM_TYPE_MISMATCH",
    "LECTURER_CONFLICT", "STUDENT_CONFLICT", "ROOM_CONFLICT",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class BookingProposal(_Frozen):
    occurrence_id: UUID
    starts_at: datetime
    room_id: UUID
    mode: ProposalMode = "schedule"

    @field_validator("starts_at")
    @classmethod
    def aware_start(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("starts_at must include a timezone offset")
        return value.astimezone(timezone.utc)


class BookingIssue(_Frozen):
    code: IssueCode
    detail: str
    booking_id: UUID | None = None
    booking_kind: Literal["class", "meeting"] | None = None
    conflicting_student_count: int = Field(default=0, ge=0)


class BookingValidation(_Frozen):
    occurrence_id: UUID
    room_id: UUID
    starts_at: datetime
    ends_at: datetime | None
    snapshot_revision: str
    issues: tuple[BookingIssue, ...]

    @computed_field
    @property
    def valid(self) -> bool:
        return not self.issues

    @property
    def reason_codes(self) -> tuple[IssueCode, ...]:
        return tuple(issue.code for issue in self.issues)


class BlockingInterval(_Frozen):
    starts_at: datetime
    ends_at: datetime
    issues: tuple[BookingIssue, ...]


class BookingValidator:
    """Reuse indexes while checking candidates against the same captured data.

    Validation does not authorize a caller, reserve resources, or save a booking.
    Cross-week moves require a correctly prepared target-week input in step 11.
    """

    def __init__(self, snapshot: SchedulingSnapshot):
        self.snapshot = snapshot
        self._requirements = {item.occurrence_id: item for item in snapshot.requirements}
        self._rooms = {item.id: item for item in snapshot.rooms}
        self._room_rules = {rule.course_type: rule.allowed_room_types for rule in snapshot.room_rules}
        self._bookings = (
            *(('class', item) for item in snapshot.class_bookings),
            *(('meeting', item) for item in snapshot.meeting_bookings),
        )

    def get_requirement(self, occurrence_id: UUID) -> ClassRequirement | None:
        return self._requirements.get(occurrence_id)

    def occurrence_issues(self, occurrence_id: UUID, mode: ProposalMode = "schedule") -> tuple[BookingIssue, ...]:
        """Shared lifecycle checks for validation and range generation."""
        item = self.get_requirement(occurrence_id)
        if item is None:
            return (BookingIssue(code="OCCURRENCE_NOT_FOUND", detail="The occurrence is not present in this week's scheduling input."),)
        if item.requirement_status == "cancelled":
            return (BookingIssue(code="OCCURRENCE_CANCELLED", detail="Explicitly reopen the teaching requirement before scheduling a replacement."),)
        if mode == "schedule" and item.booking_status in ACTIVE_BOOKING_STATUSES:
            return (BookingIssue(code="ALREADY_SCHEDULED", detail="This occurrence already has a booking; use reschedule mode to move it."),)
        if mode == "reschedule":
            if item.booking_status not in ACTIVE_BOOKING_STATUSES:
                return (BookingIssue(code="NOT_SCHEDULED", detail="Reschedule mode requires an existing active (scheduled or rescheduled) booking."),)
            if not any(booking.id == item.class_session_id and booking.occurrence_id == item.occurrence_id
                       for booking in self.snapshot.class_bookings):
                return (BookingIssue(code="ORIGINAL_BOOKING_NOT_FOUND", detail="The occurrence's original booking is missing from this snapshot."),)
        return ()

    def room_issues(self, occurrence_id: UUID, room_id: UUID) -> tuple[BookingIssue, ...]:
        """Shared active/type/capacity checks without choosing a start time."""
        item = self.get_requirement(occurrence_id)
        if item is None:
            return self.occurrence_issues(occurrence_id)
        issues = []
        room = self._rooms.get(room_id)
        if room is None:
            issues.append(BookingIssue(code="ROOM_NOT_FOUND", detail="The proposed room is not present in the scheduling input."))
        else:
            if not room.is_active:
                issues.append(BookingIssue(code="ROOM_INACTIVE", detail="The proposed room is inactive."))
            if room.capacity < item.student_count:
                issues.append(BookingIssue(code="ROOM_TOO_SMALL", detail="The room has fewer seats than the actual class roster requires."))
        allowed = self._room_rules.get(item.course_type)
        if not allowed:
            issues.append(BookingIssue(code="ROOM_POLICY_UNDEFINED", detail="No allowed room types are configured for this teaching type."))
        elif room is not None and room.room_type not in allowed:
            issues.append(BookingIssue(code="ROOM_TYPE_MISMATCH", detail="The room type is not permitted for this teaching type by the configured policy."))
        return tuple(issues)

    def blocking_intervals(
        self, occurrence_id: UUID, room_id: UUID, mode: ProposalMode = "schedule",
    ) -> tuple[BlockingInterval, ...]:
        """Shared resource blockers; callers first check occurrence_issues."""
        item = self.get_requirement(occurrence_id)
        if item is None:
            return ()
        original_id = item.class_session_id if mode == "reschedule" else None
        intervals = []
        for kind, booking in self._bookings:
            if booking.status not in ACTIVE_BOOKING_STATUSES:
                continue
            if (kind == "class" and original_id is not None and booking.id == original_id
                    and booking.occurrence_id == item.occurrence_id):
                continue
            issues = []
            if booking.lecturer_id == item.lecturer_id:
                issues.append(BookingIssue(code="LECTURER_CONFLICT", detail="The assigned lecturer has an overlapping booking.",
                                           booking_id=booking.id, booking_kind=kind))
            shared = item.student_ids & booking.student_ids
            if shared:
                issues.append(BookingIssue(code="STUDENT_CONFLICT", detail="Attending students have an overlapping booking.",
                                           booking_id=booking.id, booking_kind=kind, conflicting_student_count=len(shared)))
            if booking.room_id is not None and booking.room_id == room_id:
                issues.append(BookingIssue(code="ROOM_CONFLICT", detail="The room has an overlapping booking or reservation.",
                                           booking_id=booking.id, booking_kind=kind))
            if issues:
                intervals.append(BlockingInterval(starts_at=booking.starts_at, ends_at=booking.ends_at, issues=tuple(issues)))
        return tuple(intervals)

    def validate(self, proposal: BookingProposal) -> BookingValidation:
        issues: list[BookingIssue] = []
        ends_at: datetime | None = None

        def issue(code: IssueCode, detail: str) -> None:
            issues.append(BookingIssue(code=code, detail=detail))

        def result() -> BookingValidation:
            return BookingValidation(
                occurrence_id=proposal.occurrence_id, room_id=proposal.room_id,
                starts_at=proposal.starts_at, ends_at=ends_at,
                snapshot_revision=self.snapshot.revision, issues=tuple(issues),
            )

        requirement = self.get_requirement(proposal.occurrence_id)
        if requirement is None:
            issue("OCCURRENCE_NOT_FOUND", "The occurrence is not present in this week's scheduling input.")
            return result()
        try:
            ends_at = proposal.starts_at + timedelta(minutes=requirement.duration_minutes)
        except OverflowError:
            issue("INVALID_START_TIME", "The proposed start and course duration exceed the supported date range.")
            return result()
        lifecycle_issues = self.occurrence_issues(proposal.occurrence_id, proposal.mode)
        if lifecycle_issues:
            issues.extend(lifecycle_issues)
            return result()

        if not (self.snapshot.horizon_starts_at <= proposal.starts_at and ends_at <= self.snapshot.horizon_ends_at):
            issue("OUTSIDE_HORIZON", "The full class must fit within the selected scheduling week; load its target week first.")
            return result()
        if not any(window.starts_at <= proposal.starts_at and ends_at <= window.ends_at
                   for window in self.snapshot.opening_windows):
            issue("OUTSIDE_TEACHING_HOURS", "The full class must fit within one configured opening window on an open teaching day.")

        issues.extend(self.room_issues(proposal.occurrence_id, proposal.room_id))
        for blocking in self.blocking_intervals(proposal.occurrence_id, proposal.room_id, proposal.mode):
            if proposal.starts_at < blocking.ends_at and blocking.starts_at < ends_at:
                issues.extend(blocking.issues)
        return result()


def validate_booking(snapshot: SchedulingSnapshot, proposal: BookingProposal) -> BookingValidation:
    """Convenience entry point for checking one class proposal."""
    return BookingValidator(snapshot).validate(proposal)
