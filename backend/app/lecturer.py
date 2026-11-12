import os
import httpx
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from .auth import SessionUser, require_login, require_roles
from .config import SupabaseSettings
from .scheduling.requirements import ACTIVE_BOOKING_STATUSES

# Classes are scheduled and shown in Malaysia time (UTC+8, no daylight saving).
MY_TZ = timezone(timedelta(hours=8))


def day_start_utc(day: date) -> str:
    """Midnight at the start of a Malaysian calendar day, as the UTC instant the database compares against."""
    return datetime(day.year, day.month, day.day, tzinfo=MY_TZ).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SessionDetail(BaseModel):
    id: str
    session_date: str
    start_time: str
    end_time: str
    room_id: Optional[str] = None
    room_name: Optional[str] = None
    course_code: str
    course_type: str
    course_name: str
    intake_code: str
    group_number: int
    student_count: int
    duration_minutes: int
    required_room_type: str
    status: str
    moved: bool = False
    can_reschedule: bool = True

class RescheduleRequest(BaseModel):
    session_date: str
    start_time: str
    room_id: str
    reason: Optional[str] = None

class Supabase:
    def __init__(self, settings: SupabaseSettings, client: httpx.AsyncClient):
        self.url = os.getenv(settings.url_env, "").strip().rstrip("/")
        key = os.getenv(settings.key_env, "").strip()
        if not self.url or not key:
            raise HTTPException(503, "Supabase is not configured. Check your .env file.")
        self.headers = {"apikey": key, "Accept": "application/json"}
        if key.startswith("eyJ"):
            self.headers["Authorization"] = f"Bearer {key}"
        self.client = client

    async def get(self, table: str, params: list[tuple[str, str]]) -> list[dict]:
        try:
            res = await self.client.get(f"{self.url}/rest/v1/{table}", headers=self.headers, params=params)
            if res.status_code != 200:
                print("Supabase Error:", res.text)
                raise HTTPException(500, "Database error")
            return res.json()
        except Exception as e:
            print("Request Exception:", e)
            raise HTTPException(500, f"Failed to reach Supabase: {str(e)}")

LECTURER_OR_ADMIN = require_roles("lecturer", "admin")


def check_own_lecturer(session: SessionUser, lecturer_id: str) -> None:
    # Login: a lecturer may only use their own id; admins may use any.
    if session.role == "lecturer" and session.profile_id != lecturer_id:
        raise HTTPException(403, {"message": "You can only view and change your own classes.", "conflicts": []})


def create_lecturer_router(settings: SupabaseSettings) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["lecturer"])

    @router.get("/rooms", response_model=List[dict], dependencies=[Depends(require_login)])
    async def get_rooms(request: Request):
        db = Supabase(settings, request.app.state.http_client)
        return await db.get("rooms", [("select", "*"), ("is_active", "eq.true")])

    @router.get("/lecturers", response_model=List[dict])
    async def get_lecturers(request: Request, session: SessionUser = Depends(LECTURER_OR_ADMIN)):
        db = Supabase(settings, request.app.state.http_client)
        params = [("select", "id,full_name")]
        if session.role == "lecturer":
            params.append(("id", f"eq.{session.profile_id}"))  # a lecturer only sees themselves
        rows = await db.get("lecturers", params)
        return [{"id": r["id"], "name": r["full_name"]} for r in rows]

    @router.get("/lecturers/{lecturer_id}/timetable", response_model=List[SessionDetail])
    async def get_lecturer_timetable(
        lecturer_id: str,
        request: Request,
        start: str = Query(...),
        end: Optional[str] = None,
        session: SessionUser = Depends(LECTURER_OR_ADMIN),
    ):
        check_own_lecturer(session, lecturer_id)
        try:
            db = Supabase(settings, request.app.state.http_client)
            
            query_params = [
                ("select", "*,rooms(name)"),
                ("lecturer_id", f"eq.{lecturer_id}"),
            ]
            
            # start/end are Malaysian dates (end inclusive), so the window is [start 00:00, end+1 00:00) in UTC+8.
            try:
                first_day = date.fromisoformat(start)
                last_day = date.fromisoformat(end) if end else None
            except ValueError:
                raise HTTPException(422, detail="start and end must be dates like 2026-11-09")
            query_params.append(("starts_at", f"gte.{day_start_utc(first_day)}"))
            if last_day:
                query_params.append(("starts_at", f"lt.{day_start_utc(last_day + timedelta(days=1))}"))

            data = await db.get("class_session_details", query_params)

            results = []
            now_utc = datetime.now(timezone.utc)

            for s in data:
                raw_starts = s["starts_at"].replace(" ", "T")
                raw_ends = s["ends_at"].replace(" ", "T")

                if raw_starts.endswith("+00"):
                    raw_starts += ":00"
                if raw_ends.endswith("+00"):
                    raw_ends += ":00"

                starts_dt = datetime.fromisoformat(raw_starts).astimezone(MY_TZ)
                ends_dt = datetime.fromisoformat(raw_ends).astimezone(MY_TZ)
                
                results.append({
                "id": s["id"],
                "session_date": starts_dt.strftime("%Y-%m-%d"),
                "start_time": starts_dt.strftime("%H:%M"),
                "end_time": ends_dt.strftime("%H:%M"),
                "room_id": s.get("room_id"),
                "room_name": s.get("rooms", {}).get("name") if s.get("rooms") else None,
                "course_code": s["course_code"],
                "course_type": s["course_type"],
                "course_name": s["course_name"],
                "intake_code": "CS-2024",
                "group_number": s["group_number"],
                "student_count": 30,
                "duration_minutes": s["duration_minutes"],
                "required_room_type": s.get("required_room_type", "classroom"),
                "status": s["status"],
                "moved": s["status"] == "rescheduled",
                "can_reschedule": s["status"] in ACTIVE_BOOKING_STATUSES and starts_dt > now_utc.astimezone(MY_TZ)
            })
            return results
        except HTTPException:
            raise  # keep the real status (422, 503...) instead of turning it into a 500 below
        except Exception as e:
            # 这一行会直接把错误细节返回给前端
            import traceback
            traceback.print_exc()
            raise HTTPException(500, detail=str(e))

    @router.patch("/lecturers/{lecturer_id}/sessions/{session_id}")
    async def reschedule_session(lecturer_id: str, session_id: str, payload: RescheduleRequest, request: Request,
                                 session: SessionUser = Depends(LECTURER_OR_ADMIN)):
        check_own_lecturer(session, lecturer_id)
        db = Supabase(settings, request.app.state.http_client)
        # The class must belong to this lecturer; otherwise anyone could move any class.
        owned = await db.get("class_session_details", [("select", "id,lecturer_id,status"), ("id", f"eq.{session_id}")])
        if not owned:
            raise HTTPException(404, {"message": "Class not found.", "conflicts": []})
        if str(owned[0].get("lecturer_id")) != lecturer_id:
            raise HTTPException(403, {"message": "You can only change your own classes.", "conflicts": []})
        # Only an active class can be moved; moving must never reactivate a cancelled one.
        if owned[0].get("status") not in ACTIVE_BOOKING_STATUSES:
            raise HTTPException(409, {"message": "Only a scheduled or rescheduled class can be moved.", "conflicts": []})

        new_starts_at = f"{payload.session_date}T{payload.start_time}:00+08:00"
        url = f"{db.url}/rest/v1/class_sessions?id=eq.{session_id}"
        data = {"starts_at": new_starts_at, "room_id": payload.room_id, "status": "rescheduled"}
        
        try:
            res = await db.client.patch(url, headers=db.headers, json=data)
            if res.status_code not in [200, 204]:
                raise HTTPException(500, "Failed to update session")
        except Exception as e:
            raise HTTPException(500, f"Failed to update: {str(e)}")
            
        return {"status": "ok"}

    return router