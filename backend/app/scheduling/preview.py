"""HTTP orchestration for weekly scheduling.

`generate` is read-only. `save` (step 10) writes the reviewed preview to
class_sessions after rechecking it against fresh data. Both are admin-only
production endpoints (used by /admin/schedule, locally and on Vercel) since
12 November 2026. Only the development test page under /admin/development/
still requires development mode and a direct localhost connection."""

import hashlib
import json
import logging
import re
from html import escape
from datetime import date, timedelta
from ipaddress import ip_address
from pathlib import Path
from typing import Iterable, Literal
from urllib.parse import urlsplit
from uuid import UUID

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..auth import SessionUser, get_session, login_redirect
from ..config import CourseType, Settings
from ..student import Supabase, SupabaseWriteError
from ..observability import REQUEST_ID, event, safe_frames
from .loader import SchedulingDataError, SchedulingSnapshot, load_scheduling_snapshot
from .save import MAX_PLACEMENTS, SavedClass, SavePlacement, SaveRejected, SaveResult, prepare_rows
from .solver import ClassPlacement, ScheduleResult, StopSignal, solve_weekly_schedule

ASSETS = Path(__file__).resolve().parent / "development"
# Admin-only development test page (also requires development mode and a direct localhost connection).
PAGE_PATH = "/admin/development/scheduling-test-hayden"
# Upper bound on intakes scheduled together in one preview (the model grows with every class).
MAX_INTAKES = 100


class GenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    week_start: date = Field(description="Monday of the teaching week (YYYY-MM-DD)", examples=["2026-11-16"])
    intake_id: UUID | None = Field(default=None, description="One intake (as used by the development test page). "
                                                             "Give either intake_id or intake_ids.")
    intake_ids: list[UUID] | None = Field(default=None, min_length=1, max_length=MAX_INTAKES,
                                          description="Several intakes, scheduled together in one preview so they "
                                                      "cannot clash with each other. All their groups are included.")
    group_number: int | None = Field(default=None, gt=0, strict=True,
                                     description="Optional group within intake_id; omit for all its groups. "
                                                 "Not allowed with intake_ids.")
    run_id: UUID | None = Field(default=None, description="Chosen by the page (a random UUID) so that the same admin "
                                                          "can pause this run with POST /api/schedules/generate/stop.")

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

    @model_validator(mode="after")
    def one_scope(self):
        if (self.intake_id is None) == (self.intake_ids is None):
            raise ValueError("Give either intake_id or intake_ids")
        if self.intake_ids is not None and self.group_number is not None:
            raise ValueError("group_number can only be used with intake_id")
        return self

    @property
    def intakes(self) -> tuple[UUID, ...]:
        """The selected intakes, sorted and without repeats."""
        return tuple(sorted({self.intake_id} if self.intake_id else set(self.intake_ids), key=str))

    def scope_fields(self) -> dict:
        """scope, intake_id, intake_ids and group_number for responses."""
        intakes = self.intakes
        single = intakes[0] if len(intakes) == 1 else None
        scope = "intakes" if single is None else "intake" if self.group_number is None else "intake_group"
        return {"scope": scope, "intake_id": single, "intake_ids": list(intakes), "group_number": self.group_number}


class StopRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID = Field(description="run_id sent with the generate request")


class StopResult(BaseModel):
    stopped: bool = Field(description="True when this server is running that preview and has told it to stop. "
                                      "The generate request then returns soon with stopped=true.")


class SaveRequest(GenerationRequest):
    """The preview being saved: the same week/intake/group, its revision, and its classes."""
    snapshot_revision: str = Field(pattern=r"^[0-9a-f]{64}$", description="snapshot_revision from the preview")
    placements: list[SavePlacement] = Field(min_length=1, max_length=MAX_PLACEMENTS,
                                            description="Every placement from the preview, unchanged")


class PreviewPlacement(ClassPlacement):
    course_code: str
    course_name: str
    course_type: CourseType
    intake_id: UUID
    group_number: int
    room_name: str
    room_building: str


class UnplacedClass(BaseModel):
    """A pending class with no valid start in any room, labelled for people (from candidate_failures)."""
    occurrence_id: UUID
    course_code: str
    course_name: str
    course_type: CourseType
    intake_id: UUID
    group_number: int
    reasons: list[str]


class SchedulePreview(ScheduleResult):
    placements: tuple[PreviewPlacement, ...]
    scope: Literal["intake", "intake_group", "intakes"]
    intake_id: UUID | None = Field(description="The intake when exactly one was selected; null for several")
    intake_ids: list[UUID] = Field(description="Every selected intake, sorted")
    group_number: int | None
    unplaced: list[UnplacedClass] = Field(default_factory=list,
                                          description="Classes that cannot be placed anywhere, with readable reasons")


class PreviewErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str


class PreviewError(BaseModel):
    detail: PreviewErrorDetail


def failure(status: int, code: str, message: str, name: str = "generation_rejected") -> HTTPException:
    event(name, level=logging.WARNING, http_status=status, code=code)
    return HTTPException(status, {"code": code, "message": message, "request_id": REQUEST_ID.get()}, headers={"Cache-Control": "no-store"})


def select_scope(snapshot: SchedulingSnapshot, intakes: UUID | Iterable[UUID],
                 group_number: int | None) -> SchedulingSnapshot:
    """Narrow demand to one or more intakes (and optionally one group of a single intake),
    preserving ALL fixed bookings and actual attendance sets."""
    selected = sorted({intakes} if isinstance(intakes, UUID) else set(intakes), key=str)
    wanted = set(selected)
    requirements = tuple(item for item in snapshot.requirements
                         if item.intake_id in wanted and (group_number is None or item.group_number == group_number))
    # Bind scope even for empty groups, while keeping the complete source revision
    # as a conservative invalidation boundary for later transactional saving.
    # One intake keeps the original (version 1) form, however it was requested.
    scope = ({"scope_version": 1, "intake_id": str(selected[0])} if len(selected) == 1
             else {"scope_version": 2, "intake_ids": [str(item) for item in selected]})
    revision = hashlib.sha256(json.dumps({
        **scope, "source_revision": snapshot.revision, "group_number": group_number,
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


def origin_allowed(request: Request, cors_origins: Iterable[str]) -> bool:
    """Production guard for admin writes (works behind Vercel's proxy, so no localhost rule).

    Browsers always send Origin on a cross-origin POST; it must be this site (the host the
    browser used, which Vercel passes as Host / X-Forwarded-Host) or a configured CORS
    origin. A request without Origin (same-origin tools, tests) is allowed here and still
    needs the admin session cookie, which is SameSite=Lax."""
    origin = request.headers.get("origin")
    if origin is None or origin in cors_origins:
        return True
    hosts = {request.headers.get("host", "").lower()}
    hosts.update(item.strip().lower() for item in request.headers.get("x-forwarded-host", "").split(","))
    try:
        netloc = urlsplit(origin).netloc.lower()
    except ValueError:
        return False
    return bool(netloc) and netloc in hosts


def create_preview_router(settings: Settings) -> APIRouter:
    # One slot covers loading, solving, verification and response construction.
    # Per process; this is deliberately not a distributed job system.
    slots = anyio.CapacityLimiter(1)
    # Previews running in this process that can be paused: run_id -> (admin profile id, signal).
    # Per process like the slot; a stop request that reaches another instance finds nothing.
    runs: dict[UUID, tuple[str, StopSignal]] = {}

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

    async def same_site(request: Request):
        if not origin_allowed(request, settings.server.cors_origins):
            raise failure(403, "ORIGIN_NOT_ALLOWED", "This browser origin cannot use the scheduling tools.",
                          "access_rejected")

    async def admin_access(session: SessionUser | None = Depends(get_session)) -> SessionUser:
        if session is None:
            raise failure(401, "AUTH_REQUIRED", "Log in as an administrator to use the scheduling tools.", "access_rejected")
        if session.must_change_password:
            raise failure(403, "PASSWORD_CHANGE_REQUIRED", "Change your temporary password to continue.", "access_rejected")
        if session.role != "admin":
            raise failure(403, "ADMIN_REQUIRED", "Only administrators can use the scheduling tools.", "access_rejected")
        return session

    router = APIRouter(tags=["Scheduling"])
    # The origin check runs first, so a rejected origin never reaches the session lookup.
    admin_only = [Depends(same_site), Depends(admin_access)]
    # Development test page: development mode, direct localhost, then admin.
    development_only = [Depends(development_access)]

    @router.post(
        "/api/schedules/generate", response_model=SchedulePreview, dependencies=admin_only,
        responses={code: {"model": PreviewError} for code in (401, 403, 404, 429, 500, 502, 503, 504)},
        summary="Generate a read-only weekly schedule preview (admin)",
        description="Schedules pending occurrences for one intake (intake_id, optionally one group) or for several "
                    "intakes together (intake_ids). All existing bookings remain fixed. "
                    "Compulsory rules (opening hours, whole-minute starts, room policy, capacity, no clashes, the configured gap "
                    "between classes) are always enforced; the configured preferences (student idle time, lecturer idle time, "
                    "room fit) then rank valid timetables, and the result includes quality measurements. Never saves bookings.",
    )
    async def generate(body: GenerationRequest, request: Request, response: Response,
                       admin: SessionUser = Depends(admin_access)):
        response.headers["Cache-Control"] = "no-store"
        try:
            slots.acquire_nowait()
        except anyio.WouldBlock:
            error = failure(429, "GENERATION_BUSY", "Another preview is being generated. Try again shortly.")
            error.headers["Retry-After"] = "2"
            raise error
        stop = StopSignal()
        if body.run_id is not None:
            runs[body.run_id] = (admin.profile_id, stop)

        async def watch_for_stop():
            # Pause (stop endpoint) or a closed page (client disconnected) ends the search early.
            # Repeated because CP-SAT can miss a stop sent just as a search starts.
            while True:
                await anyio.sleep(0.5)
                if stop.requested or await request.is_disconnected():
                    stop.request()
        # A disconnected/cancelled caller must not free capacity while its worker
        # is still solving. run_sync also waits for its worker by default.
        with anyio.CancelScope(shield=True):
            try:
                db = Supabase(settings.supabase, request.app.state.http_client)
                snapshot = await load_scheduling_snapshot(db, settings.scheduling, body.week_start)
                snapshot = select_scope(snapshot, body.intakes, body.group_number)
                event("snapshot_loaded", stage="solve", pending_count=len(snapshot.pending_requirements))
                event("solver_started", stage="solve")
                solve_error = None
                async with anyio.create_task_group() as watchers:
                    watchers.start_soon(watch_for_stop)
                    try:
                        result = await anyio.to_thread.run_sync(solve_weekly_schedule, snapshot, settings.scheduling.solver,
                                                                settings.scheduling.quality, stop)
                    except Exception as exc:  # re-raised below, so it is not wrapped in an ExceptionGroup
                        solve_error = exc
                    watchers.cancel_scope.cancel()
                if solve_error is not None:
                    raise solve_error
                event("solver_completed", status=result.status, placement_count=len(result.placements),
                      duration_ms=round(result.statistics.elapsed_seconds * 1000, 2), stopped=result.stopped)
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
                unplaced = []
                for item in result.candidate_failures:
                    lesson = requirements[item.occurrence_id]
                    reasons = list(dict.fromkeys(diagnostic.detail for diagnostic in item.diagnostics))
                    unplaced.append(UnplacedClass(
                        occurrence_id=item.occurrence_id, course_code=lesson.course_code, course_name=lesson.course_name,
                        course_type=lesson.course_type, intake_id=lesson.intake_id, group_number=lesson.group_number,
                        reasons=reasons,
                    ))
                # Keep computed fields out of nested candidate input as well.
                # They are recomputed during response serialization.
                return SchedulePreview(
                    **result.model_dump(exclude={"placements"}, round_trip=True), placements=tuple(placements),
                    unplaced=unplaced, **body.scope_fields(),
                )
            except SchedulingDataError as exc:
                raise failure(502, exc.code, exc.detail) from exc
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
                if body.run_id is not None and runs.get(body.run_id, (None, None))[1] is stop:
                    del runs[body.run_id]
                slots.release()

    @router.post(
        "/api/schedules/generate/stop", response_model=StopResult, dependencies=[Depends(same_site)],
        responses={code: {"model": PreviewError} for code in (401, 403)},
        summary="Pause a running preview (admin)",
        description="Asks the preview started with this run_id by the same admin to stop searching. That generate "
                    "request then returns the best complete timetable found so far, or none, with stopped=true. "
                    "stopped=false means this server is not running it (finished already, another admin's run, or "
                    "another server instance); the page then stops waiting instead. Never saves bookings.",
    )
    async def stop_generation(body: StopRequest, response: Response, admin: SessionUser = Depends(admin_access)):
        response.headers["Cache-Control"] = "no-store"
        owner, signal = runs.get(body.run_id, (None, None))
        if signal is None or owner != admin.profile_id:
            return StopResult(stopped=False)
        signal.request()
        event("generation_stop_requested", stage="solve")
        return StopResult(stopped=True)

    @router.post(
        "/api/schedules/save", status_code=201, response_model=SaveResult, dependencies=admin_only,
        responses={code: {"model": PreviewError} for code in (401, 403, 404, 409, 429, 500, 502, 503, 504)},
        summary="Save a reviewed preview as real class bookings (admin)",
        description="Re-reads the week, rejects the save if anything changed since the preview, revalidates every class, "
                    "then inserts all classes into class_sessions in one statement (all or nothing). Each class records "
                    "the saving admin (created_by), and the database adds a schedule_changes 'create' audit row in the "
                    "same statement. Saved classes are visible immediately. There is no draft and no undo.",
    )
    async def save(body: SaveRequest, request: Request, response: Response, admin: SessionUser = Depends(admin_access)):
        response.headers["Cache-Control"] = "no-store"
        try:
            # Same slot as generation: a save never runs alongside a preview or another save.
            slots.acquire_nowait()
        except anyio.WouldBlock:
            error = failure(429, "GENERATION_BUSY", "A preview or save is already running. Try again shortly.", "save_rejected")
            error.headers["Retry-After"] = "2"
            raise error
        writing = False
        with anyio.CancelScope(shield=True):
            try:
                event("save_started", placement_count=len(body.placements))
                db = Supabase(settings.supabase, request.app.state.http_client)
                snapshot = await load_scheduling_snapshot(db, settings.scheduling, body.week_start)
                snapshot = select_scope(snapshot, body.intakes, body.group_number)
                rows = await anyio.to_thread.run_sync(prepare_rows, snapshot, body.snapshot_revision, body.placements,
                                                      admin.auth_user_id)
                event("save_validated", row_count=len(rows))
                writing = True
                saved = await db.insert("class_sessions", rows, "id,occurrence_id")
                expected = {row["occurrence_id"] for row in rows}
                if len(saved) != len(rows) or {str(row.get("occurrence_id")) for row in saved} != expected:
                    raise failure(502, "SAVE_UNCONFIRMED", "Supabase did not confirm every saved class. Generate a new "
                                  "preview to see what was saved before trying again.", "save_rejected")
                event("save_completed", saved_count=len(saved))
                return SaveResult(
                    week_start=body.week_start.isoformat(), timezone=snapshot.timezone, **body.scope_fields(),
                    snapshot_revision=body.snapshot_revision,
                    saved_count=len(saved), saved_by=admin.name or admin.email or "Administrator",
                    saved=[SavedClass(occurrence_id=row["occurrence_id"], class_session_id=row["id"]) for row in saved],
                )
            except SaveRejected as exc:
                raise failure(exc.status, exc.code, exc.message, "save_rejected") from exc
            except SchedulingDataError as exc:
                raise failure(502, exc.code, exc.detail, "save_rejected") from exc
            except SupabaseWriteError as exc:
                event("save_write_failed", level=logging.WARNING, provider_status=exc.provider_status,
                      provider_code=exc.provider_code)
                if exc.provider_code in ("PGRST204", "42703"):
                    raise failure(503, "AUDIT_NOT_INSTALLED", "The database is missing the save-audit change "
                                  "(migration 202611120002_save_audit.sql). Nothing was saved. Ask the project owner "
                                  "to apply it.", "save_rejected") from exc
                if exc.provider_code == "23505" or exc.provider_status == 409:
                    raise failure(409, "ALREADY_SAVED", "One or more of these classes were booked after the preview was "
                                  "checked. Nothing was saved. Generate a new preview.", "save_rejected") from exc
                if exc.provider_code == "42501" or exc.provider_status in (401, 403):
                    raise failure(502, "DATABASE_PERMISSION_DENIED", "The server's database key cannot write class "
                                  "bookings. Nothing was saved.", "save_rejected") from exc
                if exc.provider_code in ("23503", "23514", "P0001") or exc.provider_status == 400:
                    raise failure(409, "SAVE_REJECTED_BY_DATABASE", "The database rejected this timetable, so nothing "
                                  "was saved. Generate a new preview; report the request ID if this repeats.",
                                  "save_rejected") from exc
                raise failure(502, "DATABASE_UNAVAILABLE", "The database could not save the timetable. Nothing was "
                              "saved.", "save_rejected") from exc
            except HTTPException as exc:
                if isinstance(exc.detail, dict):
                    raise
                if writing and exc.status_code == 504:
                    raise failure(504, "SAVE_OUTCOME_UNKNOWN", "Supabase timed out while saving. The classes may or may "
                                  "not have been saved; generate a new preview to check before saving again.",
                                  "save_rejected") from exc
                code = {503: "DATABASE_NOT_CONFIGURED", 504: "DATABASE_TIMEOUT"}.get(exc.status_code, "DATABASE_UNAVAILABLE")
                raise failure(exc.status_code, code, str(exc.detail), "save_rejected") from exc
            except Exception as exc:
                event("save_failed", level=logging.ERROR, exception_type=type(exc).__name__, frames=safe_frames(exc))
                raise failure(500, "SAVE_FAILED", "The timetable could not be saved because of an internal error. "
                              "Generate a new preview to check whether anything was saved.", "save_rejected") from exc
            finally:
                slots.release()

    @router.get(PAGE_PATH, include_in_schema=False, dependencies=development_only)
    async def page(session: SessionUser | None = Depends(get_session)):
        no_store = {"Cache-Control": "no-store"}
        if session is None:
            return RedirectResponse(login_redirect(PAGE_PATH), status_code=303, headers=no_store)
        if session.role != "admin" or session.must_change_password:
            return RedirectResponse(session.home, status_code=303, headers=no_store)
        html = (ASSETS / "index.html").read_text(encoding="utf-8").replace("__CAMPUS_TIMEZONE__", escape(settings.scheduling.timezone, quote=True))
        return HTMLResponse(html, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                                           "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"})

    @router.get(PAGE_PATH + "/app.js", include_in_schema=False, dependencies=[*development_only, Depends(admin_access)])
    async def script():
        return FileResponse(ASSETS / "app.js", media_type="text/javascript", headers={"Cache-Control": "no-store"})

    @router.get(PAGE_PATH + "/style.css", include_in_schema=False, dependencies=[*development_only, Depends(admin_access)])
    async def stylesheet():
        return FileResponse(ASSETS / "style.css", media_type="text/css", headers={"Cache-Control": "no-store"})

    return router
