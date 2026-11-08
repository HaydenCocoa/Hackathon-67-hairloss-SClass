"""Read-only Supabase Data API probe. No rows or credentials leave the server."""

import os
from datetime import datetime, timezone
from time import perf_counter
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel
from typing import Literal

from .config import SupabaseSettings


class DatabaseHealth(BaseModel):
    status: Literal["connected", "not_configured", "error", "timeout"]
    message: str
    checked_at: str
    latency_ms: int | None = None


async def check_database(settings: SupabaseSettings, client: httpx.AsyncClient) -> DatabaseHealth:
    checked_at = datetime.now(timezone.utc).isoformat()

    def result(status, message, latency_ms=None):
        return DatabaseHealth(status=status, message=message, checked_at=checked_at, latency_ms=latency_ms)

    url = os.getenv(settings.url_env, "").strip().rstrip("/")
    key = os.getenv(settings.key_env, "").strip()
    if not url or not key:
        return result("not_configured", "Add the Supabase URL and server key to .env, then restart the backend.")

    try:
        parsed = urlsplit(url)
        valid_url = (
            bool(parsed.hostname)
            and not parsed.username
            and not parsed.password
            and not parsed.query
            and not parsed.fragment
            and parsed.path in ("", "/")
            and (parsed.scheme == "https" or (
                parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1")
            ))
        )
    except ValueError:
        valid_url = False
    if not valid_url:
        return result("error", "Set a valid HTTPS Supabase project URL in .env (HTTP is allowed for localhost).")

    headers = {"apikey": key, "Accept": "application/json"}
    # New sb_secret keys belong only in apikey, not a JWT Authorization header.
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"

    started = perf_counter()
    try:
        response = await client.get(
            f"{url}/rest/v1/{settings.healthcheck_table}",
            headers=headers,
            params={"select": "id", "limit": "1"},
            timeout=settings.timeout_seconds,
        )
        if response.status_code in (401, 403):
            return result("error", "Supabase rejected access. Check the server key and table permissions.")
        if response.status_code == 404:
            return result("error", "The check table was not found. Apply the database schema or check config.json.")
        if response.status_code != 200:
            return result("error", "Supabase could not complete the database query. Check the project and Data API status.")
        if not isinstance(response.json(), list):
            return result("error", "Supabase returned an unexpected response to the database query.")
    except httpx.TimeoutException:
        return result("timeout", "The database check timed out. Try again or check your Supabase project status.")
    except httpx.RequestError:
        return result("error", "Could not reach Supabase. Check the project URL and network connection.")
    except ValueError:
        return result("error", "Supabase returned an unexpected response to the database query.")

    return result("connected", "Read-only database query succeeded.", round((perf_counter() - started) * 1000))
