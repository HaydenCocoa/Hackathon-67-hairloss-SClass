"""Student Page API: a student's profile and weekly timetable.

Reads Supabase through the Data API with the server-only key, so rows are
filtered here by the student's intake/group memberships (the service key
bypasses RLS).

TODO (after login is ready): take the student from the signed-in session
instead of the URL, so students can only open their own timetable.
"""

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from .config import SupabaseSettings

STUDENT_CODE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
MAX_RANGE = timedelta(days=31)
RECENT_CHANGES = timedelta(days=14)


# ---------- Response models (also documented at /docs) ----------

class Membership(BaseModel):
    intake_id: str
    intake_code: str
    group_number: int


class StudentProfile(BaseModel):
    id: str
    student_code: str
    full_name: str
    intakes: list[Membership]


class Room(BaseModel):
    name: str
    building: str


class Change(BaseModel):
    action: str  # "cancel" | "reschedule"
    reason: str | None = None
    created_at: str
    old_starts_at: str | None = None
    new_starts_at: str | None = None
    old_room: Room | None = None
    new_room: Room | None = None


class ClassItem(BaseModel):
    id: str
    course_code: str
    course_name: str
    course_type: str
    starts_at: str
    ends_at: str
    status: str  # "scheduled" | "cancelled"
    intake_code: str
    group_number: int
    room: Room | None = None
    lecturer: str | None = None
    latest_change: Change | None = None


class MeetingItem(BaseModel):
    id: str
    starts_at: str
    ends_at: str
    status: str
    lecturer: str | None = None
    room: Room | None = None  # None = online meeting


class RecentChange(Change):
    class_session_id: str
    course_code: str
    course_name: str
    current_starts_at: str
    status: str


class Timetable(BaseModel):
    student: StudentProfile
    start: str
    end: str
    classes: list[ClassItem]
    meetings: list[MeetingItem]
    recent_changes: list[RecentChange]


# ---------- Supabase helpers ----------

class Supabase:
    def __init__(self, settings: SupabaseSettings, client: httpx.AsyncClient):
        self.url = os.getenv(settings.url_env, "").strip().rstrip("/")
        key = os.getenv(settings.key_env, "").strip()
        if not self.url or not key:
            raise HTTPException(503, "Supabase is not configured. Add SUPABASE_URL and SUPABASE_KEY to .env and restart the backend.")
        self.headers = {"apikey": key, "Accept": "application/json"}
        if key.startswith("eyJ"):
            self.headers["Authorization"] = f"Bearer {key}"
        self.client = client
        self.timeout = settings.timeout_seconds

    async def get(self, table: str, params: list[tuple[str, str]]) -> list[dict[str, Any]]:
        try:
            response = await self.client.get(
                f"{self.url}/rest/v1/{table}", headers=self.headers, params=params, timeout=self.timeout,
            )
        except httpx.TimeoutException:
            raise HTTPException(504, "Supabase timed out. Try again.")
        except httpx.RequestError:
            raise HTTPException(502, "Could not reach Supabase. Check the project URL and network.")
        if response.status_code != 200:
            raise HTTPException(502, f"Supabase could not read '{table}' (HTTP {response.status_code}).")
        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, list):
            raise HTTPException(502, "Supabase returned an unexpected response.")
        return body


def in_list(values) -> str:
    # IDs come from our own database (UUIDs), so quoting is enough.
    return "in.(" + ",".join(f'"{v}"' for v in sorted(set(values))) + ")"


def iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


async def load_student(db: Supabase, student_code: str) -> StudentProfile:
    if not STUDENT_CODE.match(student_code):
        raise HTTPException(422, "Invalid student code.")
    rows = await db.get("students", [
        ("select", "id,student_code,full_name,student_intakes(group_number,intakes(id,intake_code))"),
        ("student_code", f"eq.{student_code}"),
    ])
    if not rows:
        raise HTTPException(404, f"No student found with code {student_code}.")
    row = rows[0]
    intakes = [
        Membership(intake_id=m["intakes"]["id"], intake_code=m["intakes"]["intake_code"], group_number=m["group_number"])
        for m in row.get("student_intakes") or [] if m.get("intakes")
    ]
    intakes.sort(key=lambda m: m.intake_code)
    return StudentProfile(id=row["id"], student_code=row["student_code"], full_name=row["full_name"], intakes=intakes)


async def load_names(db: Supabase, room_ids: set, lecturer_ids: set) -> tuple[dict, dict]:
    rooms, lecturers = {}, {}
    room_ids.discard(None)
    lecturer_ids.discard(None)
    if room_ids:
        for r in await db.get("rooms", [("select", "id,name,building"), ("id", in_list(room_ids))]):
            rooms[r["id"]] = Room(name=r["name"], building=r["building"])
    if lecturer_ids:
        for l in await db.get("lecturers", [("select", "id,full_name"), ("id", in_list(lecturer_ids))]):
            lecturers[l["id"]] = l["full_name"]
    return rooms, lecturers


def to_change(row: dict, rooms: dict) -> Change:
    old, new = row.get("old_values") or {}, row.get("new_values") or {}
    return Change(
        action=row["action"], reason=row.get("reason"), created_at=row["created_at"],
        old_starts_at=old.get("starts_at"), new_starts_at=new.get("starts_at"),
        old_room=rooms.get(old.get("room_id")), new_room=rooms.get(new.get("room_id")),
    )


# ---------- Routes ----------

def create_student_router(settings: SupabaseSettings) -> APIRouter:
    router = APIRouter(prefix="/api/student", tags=["student"])

    @router.get("/{student_code}", response_model=StudentProfile)
    async def student_profile(student_code: str, request: Request):
        db = Supabase(settings, request.app.state.http_client)
        return await load_student(db, student_code)

    @router.get("/{student_code}/timetable", response_model=Timetable)
    async def student_timetable(
        student_code: str,
        request: Request,
        start: datetime = Query(description="Start of the range (ISO 8601), e.g. Monday 00:00 local time"),
        end: datetime = Query(description="End of the range (exclusive), at most 31 days after start"),
    ):
        start, end = (t if t.tzinfo else t.replace(tzinfo=timezone.utc) for t in (start, end))
        if end <= start or (end - start) > MAX_RANGE:
            raise HTTPException(422, "end must be after start and within 31 days.")
        db = Supabase(settings, request.app.state.http_client)
        student = await load_student(db, student_code)
        empty = Timetable(student=student, start=iso(start), end=iso(end), classes=[], meetings=[], recent_changes=[])

        # 1. Sections the student attends: same intake AND same group number.
        groups = {(m.intake_id, m.group_number): m.intake_code for m in student.intakes}
        section_info: dict[str, tuple[str, int]] = {}
        if groups:
            offerings = await db.get("course_offerings", [
                ("select", "id,intake_id,class_sections(id,group_number)"),
                ("intake_id", in_list(m.intake_id for m in student.intakes)),
            ])
            for o in offerings:
                for s in o.get("class_sections") or []:
                    key = (o["intake_id"], s["group_number"])
                    if key in groups:
                        section_info[s["id"]] = (groups[key], s["group_number"])

        # 2. Class sessions in range (the view adds ends_at and course details).
        sessions: list[dict] = []
        if section_info:
            sessions = await db.get("class_session_details", [
                ("select", "id,section_id,room_id,lecturer_id,starts_at,ends_at,status,course_code,course_name,course_type"),
                ("section_id", in_list(section_info)),
                ("starts_at", f"gte.{iso(start)}"),
                ("starts_at", f"lt.{iso(end)}"),
                ("order", "starts_at"),
            ])

        # 3. Recent cancellations/reschedules for the student's sections.
        changes: list[dict] = []
        if section_info:
            since = iso(datetime.now(timezone.utc) - RECENT_CHANGES)
            changes = await db.get("schedule_changes", [
                ("select", "action,reason,old_values,new_values,created_at,class_session_id,"
                           "class_sessions(id,section_id,starts_at,status)"),
                ("class_session_id", "not.is.null"),
                ("created_at", f"gte.{since}"),
                ("order", "created_at.desc"),
                ("limit", "200"),
            ])
            changes = [c for c in changes if (c.get("class_sessions") or {}).get("section_id") in section_info]

        # 4. Meetings the student is invited to.
        meeting_rows = []
        for m in await db.get("meeting_students", [
            ("select", "meeting_sessions(id,starts_at,ends_at,status,room_id,lecturer_id)"),
            ("student_id", f"eq.{student.id}"),
        ]):
            meeting = m.get("meeting_sessions")
            starts = parse_time((meeting or {}).get("starts_at"))
            if starts and start <= starts < end:
                meeting_rows.append(meeting)

        if not sessions and not changes and not meeting_rows:
            return empty

        # 5. Look up room, lecturer and course names in bulk.
        room_ids = {s.get("room_id") for s in sessions} | {m.get("room_id") for m in meeting_rows}
        for c in changes:
            room_ids |= {(c.get("old_values") or {}).get("room_id"), (c.get("new_values") or {}).get("room_id")}
        lecturer_ids = {s.get("lecturer_id") for s in sessions} | {m.get("lecturer_id") for m in meeting_rows}
        rooms, lecturers = await load_names(db, {r for r in room_ids if isinstance(r, str)}, lecturer_ids)

        latest_by_session: dict[str, Change] = {}
        for c in changes:  # newest first
            latest_by_session.setdefault(c["class_session_id"], to_change(c, rooms))

        classes = []
        for s in sessions:
            intake_code, group_number = section_info[s["section_id"]]
            classes.append(ClassItem(
                id=s["id"], course_code=s["course_code"], course_name=s["course_name"], course_type=s["course_type"],
                starts_at=s["starts_at"], ends_at=s["ends_at"], status=s["status"],
                intake_code=intake_code, group_number=group_number,
                room=rooms.get(s.get("room_id")), lecturer=lecturers.get(s.get("lecturer_id")),
                latest_change=latest_by_session.get(s["id"]),
            ))

        # Course names for recent changes whose session is outside this range.
        course_by_session = {s["id"]: (s["course_code"], s["course_name"]) for s in sessions}
        missing = {c["class_session_id"] for c in changes} - set(course_by_session)
        if missing:
            for d in await db.get("class_session_details", [
                ("select", "id,course_code,course_name"), ("id", in_list(missing)),
            ]):
                course_by_session[d["id"]] = (d["course_code"], d["course_name"])

        recent = []
        for c in changes:
            code, name = course_by_session.get(c["class_session_id"], ("", "Class"))
            recent.append(RecentChange(
                **to_change(c, rooms).model_dump(), class_session_id=c["class_session_id"],
                course_code=code, course_name=name,
                current_starts_at=c["class_sessions"]["starts_at"], status=c["class_sessions"]["status"],
            ))

        meetings = [
            MeetingItem(
                id=m["id"], starts_at=m["starts_at"], ends_at=m["ends_at"], status=m["status"],
                lecturer=lecturers.get(m.get("lecturer_id")), room=rooms.get(m.get("room_id")),
            )
            for m in sorted(meeting_rows, key=lambda m: m["starts_at"])
        ]

        return Timetable(student=student, start=iso(start), end=iso(end),
                         classes=classes, meetings=meetings, recent_changes=recent)

    return router
