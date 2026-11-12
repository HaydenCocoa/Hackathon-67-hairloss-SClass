"""FastAPI entry point: run from the repository root."""

from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .auth import (AuthCookieMiddleware, SessionCache, SessionUser, create_auth_router, get_session,
                   login_redirect, require_login, safe_next)
from .config import AppSettings, PROJECT_ROOT, Settings, load_settings
from .database import DatabaseHealth, check_database
from .observability import SchedulingTraceMiddleware, configure_scheduling_logging
from .scheduling.calendar import TeachingCalendar
from .scheduling.preview import create_preview_router
from .scheduling.reschedule import create_reschedule_router
from .student import create_student_router
from .admin import create_admin_router
from .lecturer import create_lecturer_router


def create_app(settings: Settings | None = None, frontend_dist: Path | None = None) -> FastAPI:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    settings = settings or load_settings()
    frontend_dist = frontend_dist if frontend_dist is not None else PROJECT_ROOT / "frontend" / "dist"

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_scheduling_logging()
        async with httpx.AsyncClient(follow_redirects=False) as client:
            app.state.http_client = client
            yield

    app = FastAPI(title=f"{settings.app.name} API", version="0.1.0", lifespan=lifespan)
    app.state.teaching_calendar = TeachingCalendar(settings.scheduling)
    app.state.supabase_settings = settings.supabase
    app.state.auth_sessions = SessionCache()
    app.add_middleware(AuthCookieMiddleware)
    app.add_middleware(SchedulingTraceMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.server.cors_origins,
        # PUT/DELETE + Authorization: admin page; PATCH: lecturer reschedule.
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Accept", "Content-Type", "Authorization"],
        expose_headers=["X-Request-ID"],
    )

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "service": settings.app.name}

    @app.get("/api/config", response_model=AppSettings)
    async def public_config():
        # Explicit allowlist: never serve the raw Config directory or environment.
        return settings.app

    @app.get("/api/health/database", response_model=DatabaseHealth, responses={401: {}, 503: {"model": DatabaseHealth}},
             dependencies=[Depends(require_login)])
    async def database_health():
        result = await check_database(settings.supabase, app.state.http_client)
        return JSONResponse(result.model_dump(), status_code=200 if result.status == "connected" else 503)

    app.include_router(create_auth_router())
    # Student Page (Bi Jin): profile + weekly timetable
    app.include_router(create_student_router(settings.supabase))
    # Admin rescheduling (availability + move), using the scheduling engine's rules.
    app.include_router(create_reschedule_router(settings))
    # Admin Page (Edward): courses, profiles, intakes and the university timetable
    app.include_router(create_admin_router(settings.supabase))
    app.include_router(create_preview_router(settings))

    app.include_router(create_lecturer_router(settings))  # full settings: the room policy and engine rules

    # ---------- Pages (Vue app) ----------
    # Every page except /login needs a session. The checks here cover direct loads
    # of the built app; the Vue router repeats them for the Vite dev server.

    def index_file():
        if (frontend_dist / "index.html").is_file():
            return FileResponse(frontend_dist / "index.html", headers={"Cache-Control": "no-cache"})
        return JSONResponse(
            {"message": "Build the Vue frontend with npm run build in frontend/, or use the Vite development server.", "docs": "/docs"},
            status_code=503,
        )

    def redirect(path: str) -> RedirectResponse:
        return RedirectResponse(path, status_code=303, headers={"Cache-Control": "no-store"})

    @app.get("/", include_in_schema=False)
    async def root(session: SessionUser | None = Depends(get_session)):
        return redirect(session.home if session else "/login")

    @app.get("/login", include_in_schema=False)
    async def login_page(request: Request, session: SessionUser | None = Depends(get_session)):
        if session:
            target = safe_next(request.query_params.get("next"))
            return redirect(target if target and _allowed(session, target) else session.home)
        return index_file()

    def role_page(path: str, role: str):
        async def page(session: SessionUser | None = Depends(get_session)):
            if session is None:
                return redirect(login_redirect(path))
            if session.role != role:
                return redirect(session.home)
            return index_file()
        app.get(path, include_in_schema=False)(page)

    for role, path in (("student", "/student"), ("lecturer", "/lecturer"), ("admin", "/admin"), ("admin", "/admin/schedule")):
        role_page(path, role)

    if (frontend_dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

    return app


def _allowed(session: SessionUser, path: str) -> bool:
    """After login, only follow `next` into the user's own area."""
    return path == session.home or path.startswith(session.home + "/")


app = create_app()
