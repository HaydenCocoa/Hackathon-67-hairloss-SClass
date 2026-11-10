"""FastAPI entry point: run from the repository root."""

from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import AppSettings, PROJECT_ROOT, Settings, load_settings
from .database import DatabaseHealth, check_database
from .student import create_student_router
from .admin import create_admin_router


def create_app(settings: Settings | None = None, frontend_dist: Path | None = None) -> FastAPI:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    settings = settings or load_settings()
    frontend_dist = frontend_dist if frontend_dist is not None else PROJECT_ROOT / "frontend" / "dist"

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with httpx.AsyncClient(follow_redirects=False) as client:
            app.state.http_client = client
            yield

    app = FastAPI(title=f"{settings.app.name} API", version="0.1.0", lifespan=lifespan)
    app.state.environment = settings.app.environment
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.server.cors_origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Accept", "Content-Type"],
    )

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "service": settings.app.name}

    @app.get("/api/config", response_model=AppSettings)
    async def public_config():
        # Explicit allowlist: never serve the raw Config directory or environment.
        return settings.app

    @app.get("/api/health/database", response_model=DatabaseHealth, responses={503: {"model": DatabaseHealth}})
    async def database_health():
        result = await check_database(settings.supabase, app.state.http_client)
        return JSONResponse(result.model_dump(), status_code=200 if result.status == "connected" else 503)

    # Student Page (Bi Jin): profile + weekly timetable
    app.include_router(create_student_router(settings.supabase))
    app.include_router(create_admin_router(settings.supabase))

    @app.get("/", include_in_schema=False)
    async def index():
        if (frontend_dist / "index.html").is_file():
            return FileResponse(frontend_dist / "index.html", headers={"Cache-Control": "no-cache"})
        return JSONResponse(
            {"message": "Build the Vue frontend with npm run build in frontend/, or use the Vite development server.", "docs": "/docs"},
            status_code=503,
        )

    if (frontend_dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

    return app


app = create_app()
