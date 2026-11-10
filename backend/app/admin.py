"""Admin APIs for intake management and university-wide timetable viewing.

Admin sign-in uses Supabase Auth. Every data operation verifies the user's JWT
and checks that the authenticated user is linked to public.admins.
The server-only Supabase key is never sent to the browser.
"""
import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Request, Header
from pydantic import BaseModel, Field, ConfigDict

from .config import SupabaseSettings


class IntakeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intake_code: str = Field(min_length=1, max_length=40)
    max_group: int = Field(ge=1, le=100)


class AdminSupabase:
    def __init__(self, settings: SupabaseSettings, client: httpx.AsyncClient):
        self.url = os.getenv(settings.url_env, "").strip().rstrip("/")
        self.key = os.getenv(settings.key_env, "").strip()
        if not self.url or not self.key:
            raise HTTPException(503, "Supabase is not configured.")
        self.client = client
        self.timeout = settings.timeout_seconds

    def headers(self, token: str | None = None):
        h = {"apikey": self.key, "Accept": "application/json"}
        if self.key.startswith("eyJ"):
            h["Authorization"] = f"Bearer {self.key}"
        if token:
            h["Authorization"] = f"Bearer {token}"
        return h

    async def request(self, method: str, path: str, *, token: str | None = None,
                      params=None, json=None, prefer=None):
        headers = self.headers(token)
        if prefer:
            headers["Prefer"] = prefer
        try:
            response = await self.client.request(
                method, f"{self.url}{path}", headers=headers, params=params,
                json=json, timeout=self.timeout,
            )
        except httpx.TimeoutException:
            raise HTTPException(504, "Supabase timed out. Please try again.")
        except httpx.RequestError:
            raise HTTPException(502, "Could not reach Supabase.")
        if response.status_code >= 400:
            # Supabase Auth uses HTTP 400 for invalid email/password credentials.
            if path.startswith("/auth/v1/token") and response.status_code in (400, 401):
                raise HTTPException(401, "Email or password is incorrect.")
            # Do not return upstream details which can contain database internals.
            if response.status_code in (401, 403):
                raise HTTPException(401, "Your session is invalid or has expired.")
            if response.status_code == 409:
                raise HTTPException(409, "This record conflicts with existing data.")
            if response.status_code == 404:
                raise HTTPException(404, "The requested record was not found.")
            if response.status_code in (400, 422):
                raise HTTPException(400, "The request violates a database constraint. Check related records and field values.")
            raise HTTPException(502, "Supabase could not complete the request.")
        if response.status_code == 204 or not response.content:
            return []
        try:
            data = response.json()
        except ValueError:
            return []
        return data if isinstance(data, list) else data

    async def verify_admin(self, token: str):
        if not token:
            raise HTTPException(401, "Please sign in with an administrator account.")
        user = await self.request("GET", "/auth/v1/user", token=token)
        user_id = user.get("id") if isinstance(user, dict) else None
        if not user_id:
            raise HTTPException(401, "Your session is invalid or has expired.")
        rows = await self.request(
            "GET", "/rest/v1/admins",
            params={"select": "id,full_name", "auth_user_id": f"eq.{user_id}", "limit": "1"},
        )
        if not rows:
            raise HTTPException(403, "This account is not registered as an administrator.")
        return {"id": rows[0]["id"], "full_name": rows[0]["full_name"], "email": user.get("email")}


LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


def dev_bypass_active(request: Request) -> bool:
    """Local-development escape hatch while the shared login is being built.

    Only active when ALL of these hold: ADMIN_DEV_BYPASS=1 in .env, the app
    environment in Config/config.json is "development", and the request comes
    from the local machine. Never enable this on a deployed server.
    """
    if os.getenv("ADMIN_DEV_BYPASS", "").strip() != "1":
        return False
    if getattr(request.app.state, "environment", "") != "development":
        return False
    return bool(request.client) and request.client.host in LOOPBACK_HOSTS


def create_admin_router(settings: SupabaseSettings) -> APIRouter:
    router = APIRouter(prefix="/api/admin", tags=["admin"])

    def db(request: Request):
        return AdminSupabase(settings, request.app.state.http_client)

    async def require_admin(request: Request, authorization: str | None):
        if dev_bypass_active(request):
            # Server-side key is used for data access; no user token needed.
            return db(request), {"id": None, "full_name": "Dev Administrator", "email": "dev@localhost"}, ""
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(401, "Please sign in with an administrator account.")
        token = authorization.split(" ", 1)[1].strip()
        client = db(request)
        admin = await client.verify_admin(token)
        return client, admin, token

    @router.get("/dev-bypass")
    async def dev_bypass_status(request: Request):
        return {"enabled": dev_bypass_active(request)}

    @router.get("/me")
    async def me(request: Request, authorization: str | None = Header(default=None)):
        _, admin, _ = await require_admin(request, authorization)
        return admin

    @router.get("/intakes")
    async def list_intakes(request: Request, authorization: str | None = Header(default=None)):
        client, _, _ = await require_admin(request, authorization)
        return await client.request(
            "GET", "/rest/v1/intakes",
            params={"select": "id,intake_code,max_group", "order": "intake_code.asc"},
        )

    @router.post("/intakes", status_code=201)
    async def create_intake(payload: IntakeInput, request: Request,
                            authorization: str | None = Header(default=None)):
        client, _, _ = await require_admin(request, authorization)
        clean = payload.intake_code.strip().upper()
        if not clean:
            raise HTTPException(422, "Intake code cannot be empty.")
        rows = await client.request(
            "POST", "/rest/v1/intakes",
            json={"intake_code": clean, "max_group": payload.max_group},
            params={"select": "id,intake_code,max_group"},
            prefer="return=representation",
        )
        return rows[0] if rows else {}

    @router.patch("/intakes/{intake_id}")
    async def update_intake(intake_id: str, payload: IntakeInput, request: Request,
                            authorization: str | None = Header(default=None)):
        client, _, _ = await require_admin(request, authorization)
        clean = payload.intake_code.strip().upper()
        if not clean:
            raise HTTPException(422, "Intake code cannot be empty.")
        rows = await client.request(
            "PATCH", "/rest/v1/intakes",
            params={"id": f"eq.{intake_id}", "select": "id,intake_code,max_group"},
            json={"intake_code": clean, "max_group": payload.max_group},
            prefer="return=representation",
        )
        if not rows:
            raise HTTPException(404, "Intake not found.")
        return rows[0]

    @router.delete("/intakes/{intake_id}", status_code=204)
    async def delete_intake(intake_id: str, request: Request,
                            authorization: str | None = Header(default=None)):
        client, _, _ = await require_admin(request, authorization)
        # FK constraints intentionally prevent deleting intakes still used by memberships or offerings.
        await client.request("DELETE", "/rest/v1/intakes", params={"id": f"eq.{intake_id}"})
        return None

    @router.get("/timetable")
    async def university_timetable(request: Request, start: datetime, end: datetime,
                                   intake_id: str | None = None,
                                   authorization: str | None = Header(default=None)):
        client, _, _ = await require_admin(request, authorization)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        if end <= start or (end - start).days > 31:
            raise HTTPException(422, "Choose a valid date range of no more than 31 days.")
        params = {
            "select": "id,section_id,room_id,starts_at,ends_at,status,group_number,intake_id,course_code,course_name,course_type,lecturer_id",
            "starts_at": f"gte.{start.astimezone(timezone.utc).isoformat()}",
            "and": f"(starts_at.lt.{end.astimezone(timezone.utc).isoformat()})",
            "order": "starts_at.asc",
        }
        if intake_id:
            params["intake_id"] = f"eq.{intake_id}"
        sessions = await client.request("GET", "/rest/v1/class_session_details", params=params)
        room_ids = sorted({s["room_id"] for s in sessions if s.get("room_id")})
        lecturer_ids = sorted({s["lecturer_id"] for s in sessions if s.get("lecturer_id")})
        intake_ids = sorted({s["intake_id"] for s in sessions if s.get("intake_id")})
        async def lookup(table, ids, select):
            if not ids:
                return []
            return await client.request(
                "GET", f"/rest/v1/{table}",
                params={"select": select, "id": f"in.({','.join(ids)})"},
            )
        rooms, lecturers, intakes = await __import__("asyncio").gather(
            lookup("rooms", room_ids, "id,name,building"),
            lookup("lecturers", lecturer_ids, "id,full_name"),
            lookup("intakes", intake_ids, "id,intake_code"),
        )
        room_map = {x["id"]: x for x in rooms}
        lecturer_map = {x["id"]: x for x in lecturers}
        intake_map = {x["id"]: x for x in intakes}
        return [{
            **s,
            "room": room_map.get(s.get("room_id")),
            "lecturer": lecturer_map.get(s.get("lecturer_id")),
            "intake": intake_map.get(s.get("intake_id")),
        } for s in sessions]

    return router
