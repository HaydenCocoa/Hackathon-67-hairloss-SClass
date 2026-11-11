"""Allowlisted scheduling traces; never log request/provider bodies or secrets."""

import json
import logging
from contextvars import ContextVar
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock
from time import perf_counter
from traceback import extract_tb
from uuid import uuid4

from .config import PROJECT_ROOT

LOGGER = logging.getLogger("sclass.scheduling")
REQUEST_ID: ContextVar[str] = ContextVar("scheduling_request_id", default="-")
_SETUP_LOCK = Lock()
_FIELDS = {"http_status", "provider_status", "provider_code", "rpc", "stage", "duration_ms", "code",
           "pending_count", "placement_count", "status", "exception_type", "frames"}


class TraceFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # Deliberately ignore message interpolation, exc_info, locals, headers,
        # payloads and any unrecognized LogRecord extras.
        return json.dumps({"timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
                           "level": record.levelname, **getattr(record, "trace_fields", {"event": "unstructured_log_omitted"})},
                          separators=(",", ":"))


def configure_scheduling_logging(log_directory: Path | None = None):
    with _SETUP_LOCK:
        if any(getattr(handler, "sclass_trace", False) for handler in LOGGER.handlers):
            return
        LOGGER.setLevel(logging.INFO)
        LOGGER.propagate = False
        formatter = TraceFormatter()
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        console.sclass_trace = True
        LOGGER.addHandler(console)
        try:
            directory = log_directory if log_directory is not None else PROJECT_ROOT / "logs"
            directory.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(directory / "scheduling.log", maxBytes=5 * 1024 * 1024, backupCount=2, encoding="utf-8")
            handler.setFormatter(formatter)
            handler.sclass_trace = True
            LOGGER.addHandler(handler)
        except OSError as exc:
            event("file_logging_unavailable", level=logging.WARNING, exception_type=type(exc).__name__)


def event(name: str, *, level: int = logging.INFO, **fields):
    LOGGER.log(level, "", extra={"trace_fields": {
        "event": name, "request_id": REQUEST_ID.get(), **{key: value for key, value in fields.items() if key in _FIELDS},
    }})


def safe_frames(exc: Exception) -> list[dict]:
    """Retain stack locations without exception text, source lines or variables."""
    return [{"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
            for frame in extract_tb(exc.__traceback__)[-12:]]


class SchedulingTraceMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") != "/api/schedules/generate":
            return await self.app(scope, receive, send)
        # Generate locally rather than accepting a caller-supplied log value.
        token = REQUEST_ID.set(uuid4().hex)
        started, http_status = perf_counter(), 500
        event("request_started")

        async def traced_send(message):
            nonlocal http_status
            if message["type"] == "http.response.start":
                http_status = message["status"]
                message = {**message, "headers": [
                    (name, value) for name, value in message.get("headers", []) if name.lower() != b"x-request-id"
                ] + [(b"x-request-id", REQUEST_ID.get().encode("ascii"))]}
            await send(message)

        try:
            await self.app(scope, receive, traced_send)
        except Exception as exc:
            event("request_crashed", level=logging.ERROR, exception_type=type(exc).__name__, frames=safe_frames(exc))
            raise
        finally:
            event("request_completed", http_status=http_status, duration_ms=round((perf_counter() - started) * 1000, 2))
            REQUEST_ID.reset(token)
