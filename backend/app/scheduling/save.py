"""Step 10: check a reviewed preview against fresh data and turn it into booking rows.

There is no stored draft. The admin's page sends back the preview it is showing;
the server trusts only the occurrence, room and start time of each class and
re-derives everything else (section, lecturer, duration, roster) from the database.
"""

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .loader import SchedulingSnapshot
from .solver import ClassPlacement, ScheduleVerificationError, verify_placements
from .validator import BookingProposal, BookingValidator

MAX_PLACEMENTS = 1000


class SaveRejected(Exception):
    """A safe, expected refusal. Nothing has been written when this is raised."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(code)
        self.status, self.code, self.message = status, code, message


class SavePlacement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    occurrence_id: UUID
    room_id: UUID
    starts_at: datetime = Field(description="UTC start from the preview, unchanged")

    @field_validator("starts_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("starts_at must include a timezone offset")
        return value.astimezone(timezone.utc)


class SavedClass(BaseModel):
    occurrence_id: UUID
    class_session_id: UUID


class SaveResult(BaseModel):
    status: Literal["SAVED"] = "SAVED"
    week_start: str
    timezone: str
    scope: Literal["intake", "intake_group"]
    intake_id: UUID
    group_number: int | None
    snapshot_revision: str
    saved_count: int
    saved_by: str = Field(description="Name of the admin recorded in the save audit (schedule_changes)")
    saved: list[SavedClass]


def prepare_rows(snapshot: SchedulingSnapshot, revision: str, placements: list[SavePlacement],
                 created_by: str) -> list[dict]:
    """Return class_sessions rows, or raise SaveRejected. `snapshot` must already be
    narrowed to the request's intake/group with preview.select_scope. `created_by` is
    the admin's Supabase Auth user id; a database trigger turns it into one
    schedule_changes 'create' row per class in the same insert."""
    if snapshot.revision != revision:
        raise SaveRejected(409, "PREVIEW_STALE",
                           "The week's bookings or teaching data changed since this preview was generated, "
                           "or it has already been saved. Nothing was saved. Generate a new preview and review it.")
    pending = {item.occurrence_id: item for item in snapshot.pending_requirements}
    ids = [item.occurrence_id for item in placements]
    if len(ids) != len(set(ids)) or set(ids) != set(pending):
        raise SaveRejected(422, "PLACEMENTS_INCOMPLETE",
                           "Save the whole preview: every pending class in the selected intake/group must be "
                           "included exactly once. Nothing was saved.")
    validator = BookingValidator(snapshot)
    checked_placements = []
    for item in placements:
        checked = validator.validate(BookingProposal(occurrence_id=item.occurrence_id, room_id=item.room_id,
                                                     starts_at=item.starts_at))
        if not checked.valid:
            codes = ", ".join(sorted(set(checked.reason_codes)))
            raise SaveRejected(409, "PLACEMENT_CONFLICT",
                               f"A class in this preview does not pass booking validation ({codes}). "
                               "Nothing was saved. Generate a new preview.")
        source = pending[item.occurrence_id]
        checked_placements.append(ClassPlacement(
            occurrence_id=item.occurrence_id, section_id=source.section_id, lecturer_id=source.lecturer_id,
            room_id=item.room_id, starts_at=item.starts_at, ends_at=checked.ends_at, student_count=source.student_count,
        ))
    try:
        # Same check the solver runs on its own output: full coverage, validation,
        # and no shared room/lecturer/student between the new classes themselves.
        verify_placements(snapshot, tuple(checked_placements))
    except ScheduleVerificationError as exc:
        raise SaveRejected(409, "PLACEMENT_CONFLICT",
                           "Classes in this preview overlap for a shared room, lecturer or student. "
                           "Nothing was saved. Generate a new preview.") from exc
    return [{
        "occurrence_id": str(item.occurrence_id), "section_id": str(item.section_id), "room_id": str(item.room_id),
        "starts_at": item.starts_at.isoformat(), "status": "scheduled", "created_by": created_by,
    } for item in checked_placements]
