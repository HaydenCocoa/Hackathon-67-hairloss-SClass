"""Database-backed weekly demand; no timetable generation or public write API."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ..student import Supabase


class TeachingPlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_id: UUID
    first_week_start: date
    week_count: int = Field(gt=0, strict=True)
    occurrences_per_week: int = Field(default=1, gt=0, strict=True)
    timezone: str = "Asia/Kuala_Lumpur"

    @field_validator("first_week_start")
    @classmethod
    def validate_monday(cls, value: date) -> date:
        if value.weekday() != 0:
            raise ValueError("first_week_start must be a Monday")
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("timezone must be an available IANA timezone") from exc
        return value


class TeachingOccurrence(BaseModel):
    occurrence_id: UUID
    plan_id: UUID
    section_id: UUID
    original_week_start: date
    target_week_start: date
    teaching_week_number: int = Field(gt=0)
    occurrence_number: int = Field(gt=0)
    requirement_status: Literal["required", "cancelled"]
    timezone: str
    class_session_id: UUID | None
    booking_status: Literal["scheduled", "cancelled"] | None
    starts_at: datetime | None
    room_id: UUID | None
    needs_scheduling: bool
    group_number: int = Field(gt=0)
    intake_id: UUID
    lecturer_id: UUID
    course_id: UUID
    course_code: str
    course_name: str
    course_type: Literal["lecture", "tutorial", "lab", "others"]
    duration_minutes: int = Field(gt=0)


async def load_weekly_requirements(
    db: Supabase, week_start: date, *, pending_only: bool = False,
) -> list[TeachingOccurrence]:
    """Read one target week's demand, including explicit make-up requirements.

    This internal function uses the existing server-only Supabase reader. It is
    not exposed without authorization as a new HTTP endpoint. Pagination keeps
    large weeks from silently losing requirements at the Data API row limit.
    """
    if isinstance(week_start, datetime) or week_start.weekday() != 0:
        raise ValueError("week_start must be a Monday date")
    params = [
        # Select the scheduling contract explicitly; ignore a legacy room field if present in an older view.
        ("select", "occurrence_id,plan_id,section_id,original_week_start,target_week_start,teaching_week_number,"
                   "occurrence_number,requirement_status,timezone,class_session_id,booking_status,starts_at,room_id,"
                   "needs_scheduling,group_number,intake_id,lecturer_id,course_id,course_code,course_name,course_type,duration_minutes"),
        ("target_week_start", f"eq.{week_start.isoformat()}"),
        ("order", "occurrence_id.asc"),
        ("limit", "500"),
    ]
    if pending_only:
        params.append(("needs_scheduling", "eq.true"))
    result: list[TeachingOccurrence] = []
    seen: set[UUID] = set()
    while True:
        rows = await db.get("teaching_occurrence_details", [*params, ("offset", str(len(result)))])
        if not rows:
            return result
        try:
            page = [TeachingOccurrence.model_validate(row) for row in rows]
        except ValidationError as exc:
            raise HTTPException(502, "Supabase returned invalid teaching requirements.") from exc
        for occurrence in page:
            if occurrence.occurrence_id in seen or occurrence.target_week_start != week_start:
                raise HTTPException(502, "Supabase returned inconsistent teaching requirements.")
            if pending_only and not occurrence.needs_scheduling:
                raise HTTPException(502, "Supabase returned inconsistent teaching requirements.")
            seen.add(occurrence.occurrence_id)
        result.extend(page)
