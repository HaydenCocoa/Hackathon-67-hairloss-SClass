"""Development-only, read-only HTTP orchestration for weekly scheduling."""

import hashlib
import json
import logging
import re
from html import escape
from datetime import date, timedelta
from ipaddress import ip_address
from pathlib import Path
from typing import Literal
from uuid import UUID

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..config import CourseType, Settings
from ..student import Supabase, SupabaseRPCError
from ..observability import REQUEST_ID, event, safe_frames
from .loader import SchedulingDataError, SchedulingSnapshot, load_scheduling_snapshot
from .solver import ClassPlacement, ScheduleResult, solve_weekly_schedule

ASSETS = Path(__file__).resolve().parent / "development"
PAGE_PATH = "/development/scheduling-test-hayden"


class GenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    week_start: date = Field(description="Monday of the teaching week (YYYY-MM-DD)", examples=["2026-11-16"])
    intake_id: UUID = Field(description="Generate pending classes for this intake only")
    group_number: int | None = Field(default=None, gt=0, strict=True, description="Optional group within the intake; omit for all its groups")

    @field_validator("week_start", mode="before")
    @classmethod
    def date_string(cls, value):
        if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            raise ValueError("week_start must be a YYYY-MM-DD date string")
        return value

    @field_validator("week_start")
    @classmethod
    def monday(cls, value: date) -> date:
        if value.weekday() != 0:
            raise ValueError("week_start must be a Monday")
        try:
            value + timedelta(days=7)
        except OverflowError as exc:
            raise ValueError("week_start must allow a complete following week boundary") from exc
        return value


class PreviewPlacement(ClassPlacement):
    course_code: str
    course_name: str
    course_type: CourseType
    intake_id: UUID
    group_number: int
    room_name: str
    room_building: str


class SchedulePreview(ScheduleResult):
    placements: tuple[PreviewPlacement, ...]
    scope: Literal["intake", "intake_group"]
    intake_id: UUID
    group_number: int | None
    quality_optimized: Literal[False] = False
    quality: None = None


class PreviewErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str


class PreviewError(BaseModel):
    detail: PreviewErrorDetail


def failure(status: int, code: str, message: str) -> HTTPException:
    event("generation_rejected", level=logging.WARNING, http_status=status, code=code)
    return HTTPException(status, {"code": code, "message": message, "request_id": REQUEST_ID.get()}, headers={"Cache-Control": "no-store"})


def select_scope(snapshot: SchedulingSnapshot, intake_id: UUID, group_number: int | None) -> SchedulingSnapshot:
    """Narrow demand, preserving ALL fixed bookings and actual attendance sets."""
    requirements = tuple(item for item in snapshot.requirements
                         if item.intake_id == intake_id and (group_number is None or item.group_number == group_number))
    # Bind scope even for empty groups, while keeping the complete source revision
    # as a conservative invalidation boundary for later transactional saving.
    revision = hashlib.sha256(json.dumps({
        "scope_version": 1, "source_revision": snapshot.revision,
        "intake_id": str(intake_id), "group_number": group_number,
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return snapshot.model_copy(update={"requirements": requirements, "revision": revision})


def _loopback(value: str) -> bool:
    if value.lower() == "localhost":
        return True
    try:
        address = ip_address(value)
        return address.is_loopback or bool(getattr(address, "ipv4_mapped", None) and address.ipv4_mapped.is_loopback)
    except ValueError:
        return False


def create_preview_router(settings: Settings) -> APIRouter:
    # One slot covers loading, solving, verification and response construction.
    # Per process; this is deliberately not a distributed job system.
    slots = anyio.CapacityLimiter(1)

    async def development_access(request: Request):
        if settings.app.environment != "development":
            raise failure(404, "DEVELOPMENT_DISABLED", "Scheduling development tools are disabled in this environment.")
        forwarded = any(key in request.headers for key in ("forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto"))
        peer = request.client.host if request.client else ""
        host = request.url.hostname or ""
        if forwarded or not _loopback(peer) or not _loopback(host):
            raise failure(403, "LOCAL_ACCESS_ONLY", "Scheduling development tools require a direct localhost connection.")
        origin = request.headers.get("origin")
        allowed = {str(request.base_url).rstrip("/"), *settings.server.cors_origins}
        if origin is not None and origin not in allowed:
            raise failure(403, "ORIGIN_NOT_ALLOWED", "This browser origin cannot use scheduling development tools.")

    router = APIRouter(dependencies=[Depends(development_access)], tags=["Scheduling development"])

    @router.post(
        "/api/schedules/generate", response_model=SchedulePreview,
        responses={code: {"model": PreviewError} for code in (403, 404, 429, 500, 502, 503, 504)},
        summary="Generate a read-only weekly schedule preview (local development)",
        description="Schedules pending occurrences for one intake and optionally one group. All existing bookings remain fixed. Never saves bookings. Quality optimization is postponed.",
    )
    async def generate(body: GenerationRequest, request: Request, response: Response):
        response.headers["Cache-Control"] = "no-store"
        try:
            slots.acquire_nowait()
        except anyio.WouldBlock:
            error = failure(429, "GENERATION_BUSY", "Another preview is being generated. Try again shortly.")
            error.headers["Retry-After"] = "2"
            raise error
        # A disconnected/cancelled caller must not free capacity while its worker
        # is still solving. run_sync also waits for its worker by default.
        with anyio.CancelScope(shield=True):
            try:
                db = Supabase(settings.supabase, request.app.state.http_client)
                snapshot = await load_scheduling_snapshot(db, settings.scheduling, body.week_start)
                snapshot = select_scope(snapshot, body.intake_id, body.group_number)
                event("snapshot_loaded", stage="solve", pending_count=len(snapshot.pending_requirements))
                event("solver_started", stage="solve")
                result = await anyio.to_thread.run_sync(solve_weekly_schedule, snapshot, settings.scheduling.solver)
                event("solver_completed", status=result.status, placement_count=len(result.placements),
                      duration_ms=round(result.statistics.elapsed_seconds * 1000, 2))
                if result.status == "MODEL_INVALID":
                    raise failure(500, "MODEL_INVALID", "The scheduling model could not be processed.")
                requirements = {item.occurrence_id: item for item in snapshot.requirements}
                rooms = {item.id: item for item in snapshot.rooms}
                placements = []
                for item in result.placements:
                    lesson, room = requirements[item.occurrence_id], rooms[item.room_id]
                    placements.append(PreviewPlacement(
                        **item.model_dump(), course_code=lesson.course_code, course_name=lesson.course_name,
                        course_type=lesson.course_type, intake_id=lesson.intake_id, group_number=lesson.group_number,
                        room_name=room.name, room_building=room.building,
                    ))
                # Keep computed fields out of nested candidate input as well.
                # They are recomputed during response serialization.
                return SchedulePreview(
                    **result.model_dump(exclude={"placements"}, round_trip=True), placements=tuple(placements),
                    scope="intake" if body.group_number is None else "intake_group",
                    intake_id=body.intake_id, group_number=body.group_number,
                )
            except SchedulingDataError as exc:
                raise failure(502, exc.code, exc.detail) from exc
            except SupabaseRPCError as exc:
                raise failure(exc.status_code, exc.code, str(exc.detail)) from exc
            except HTTPException as exc:
                if isinstance(exc.detail, dict):
                    raise
                code = {503: "DATABASE_NOT_CONFIGURED", 504: "DATABASE_TIMEOUT"}.get(exc.status_code, "DATABASE_UNAVAILABLE")
                raise failure(exc.status_code, code, str(exc.detail)) from exc
            except Exception as exc:
                # Never reflect provider data, input rosters or exception text.
                event("generation_failed", level=logging.ERROR, exception_type=type(exc).__name__, frames=safe_frames(exc))
                raise failure(500, "GENERATION_FAILED", "The preview could not be verified or generated. No bookings were saved.") from exc
            finally:
                slots.release()

    @router.get(PAGE_PATH, include_in_schema=False)
    async def page():
        html = (ASSETS / "index.html").read_text(encoding="utf-8").replace("__CAMPUS_TIMEZONE__", escape(settings.scheduling.timezone, quote=True))
        return HTMLResponse(html, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                                           "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"})

    @router.get(PAGE_PATH + "/app.js", include_in_schema=False)
    async def script():
        return FileResponse(ASSETS / "app.js", media_type="text/javascript", headers={"Cache-Control": "no-store"})

    @router.get(PAGE_PATH + "/style.css", include_in_schema=False)
    async def stylesheet():
        return FileResponse(ASSETS / "style.css", media_type="text/css", headers={"Cache-Control": "no-store"})

    return router
