import asyncio
import os
import httpx
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from .auth import SessionUser, require_login, require_roles
from .config import SupabaseSettings

# Classes are scheduled and shown in Malaysia time (UTC+8, no daylight saving).
MY_TZ = timezone(timedelta(hours=8))

# A class that is still going ahead. "rescheduled" = it was moved at least once.
ACTIVE_STATUSES = ("scheduled", "rescheduled")

# Timetable rules, used both to check a move and to choose the times that are suggested.
WORK_ISO_DAYS = (1, 2, 3, 4, 5)        # Monday to Friday
OPEN_MIN, CLOSE_MIN = 8 * 60, 18 * 60  # a class starts at 08:00 or later and ends by 18:00
STEP_MIN = 30                          # suggested start times are every 30 minutes
GAP = timedelta(minutes=15)            # between classes of the same room, lecturer or students
ROOM_TYPES = {                         # which room types a course type may use
    "lecture": ("classroom", "auditorium"),
    "tutorial": ("classroom",),
    "lab": ("lab",),
}
DEFAULT_ROOM_TYPES = ("classroom", "auditorium")


def allowed_room_types(course_type: str) -> tuple:
    return ROOM_TYPES.get(course_type, DEFAULT_ROOM_TYPES)


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
    allowed_room_types: List[str] = []
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


def parse_ts(value: str) -> datetime:
    """Parse a timestamp as Supabase prints it ("2026-11-11 09:00:00+00") into an aware datetime."""
    text = value.replace(" ", "T")
    if text.endswith("+00"):
        text += ":00"
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def day_start_utc_dt(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=MY_TZ)


def utc_text(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def without_removed(db: "Supabase", rows: list[dict]) -> list[dict]:
    """Leave out classes that were removed (class_sessions.removed_at is set); they no longer occupy anything."""
    ids = [str(r["id"]) for r in rows if r.get("id")]
    if not ids:
        return rows
    gone = await db.get("class_sessions", [("select", "id"), ("removed_at", "not.is.null"), ("id", f"in.({','.join(ids)})")])
    removed = {str(g["id"]) for g in gone}
    return [r for r in rows if str(r.get("id")) not in removed]


OWNED_SELECT = "id,lecturer_id,status,starts_at,room_id,section_id,intake_id,group_number,duration_minutes,course_type"


async def get_own_session(db: "Supabase", lecturer_id: str, session_id: str) -> dict:
    """The class, if it exists, belongs to this lecturer and has not been cancelled."""
    rows = await db.get("class_session_details", [("select", OWNED_SELECT), ("id", f"eq.{session_id}")])
    rows = await without_removed(db, rows)
    if not rows:
        raise HTTPException(404, {"message": "Class not found.", "conflicts": []})
    if str(rows[0].get("lecturer_id")) != lecturer_id:
        raise HTTPException(403, {"message": "You can only change your own classes.", "conflicts": []})
    if rows[0].get("status") not in ACTIVE_STATUSES:
        raise HTTPException(409, {"message": "A cancelled class cannot be rescheduled.", "conflicts": []})
    return rows[0]


async def load_students(db: "Supabase", moving: dict) -> tuple[list[str], set]:
    """Students in the class's intake and group, and every (intake, group) any of them belongs to."""
    group_students = await db.get("student_intakes", [
        ("select", "student_id"),
        ("intake_id", f"eq.{moving['intake_id']}"),
        ("group_number", f"eq.{moving['group_number']}"),
    ])
    student_ids = [r["student_id"] for r in group_students]
    groups = {(str(moving["intake_id"]), moving["group_number"])}
    if student_ids:
        memberships = await db.get("student_intakes", [
            ("select", "intake_id,group_number"),
            ("student_id", f"in.({','.join(student_ids)})"),
        ])
        groups |= {(str(r["intake_id"]), r["group_number"]) for r in memberships}
    return student_ids, groups


async def suggest_slots(db: "Supabase", moving: dict, lecturer_id: str, wanted_day: date, wanted_min: int,
                        flex_days: int, limit: int) -> list[dict]:
    """Free slots near the requested day and time, best first: no room, lecturer or student clash,
    and a room of the right type and size. Follows the same rules as lecturer_reschedule_class."""
    now = datetime.now(timezone.utc)
    duration = timedelta(minutes=moving["duration_minutes"])
    current_start = parse_ts(moving["starts_at"])
    days = [(offset, wanted_day + timedelta(days=offset)) for offset in range(-flex_days, flex_days + 1)]
    days = [(o, d) for o, d in days if d.isoweekday() in WORK_ISO_DAYS and day_start_utc_dt(d + timedelta(days=1)) > now]
    if not days:
        return []
    range_start = day_start_utc_dt(days[0][1])
    range_end = day_start_utc_dt(days[-1][1] + timedelta(days=1))

    student_ids, groups = await load_students(db, moving)
    kinds = allowed_room_types(moving["course_type"])
    room_filter = [("select", "id,name,building,capacity,room_type"), ("is_active", "eq.true"),
                   ("room_type", f"in.({','.join(kinds)})")]
    rooms = [r for r in await db.get("rooms", room_filter) if r["capacity"] >= len(student_ids)]
    rooms.sort(key=lambda r: (r["capacity"], r["name"]))  # the smallest room that fits first
    if not rooms:
        return []

    window = [("starts_at", f"lt.{utc_text(range_end + GAP)}"), ("ends_at", f"gt.{utc_text(range_start - GAP)}")]
    sessions = await db.get("class_session_details", [
        ("select", "id,room_id,lecturer_id,intake_id,group_number,starts_at,ends_at"),
        ("status", f"in.({','.join(ACTIVE_STATUSES)})"),
        ("id", f"neq.{moving['id']}"),
        *window,
    ])
    sessions = await without_removed(db, sessions)
    meetings = await db.get("meeting_sessions", [
        ("select", "id,room_id,lecturer_id,starts_at,ends_at"), ("status", "eq.scheduled"), *window,
    ])
    attendees: set[str] = set()
    if meetings and student_ids:
        rows = await db.get("meeting_students", [
            ("select", "meeting_id"),
            ("meeting_id", f"in.({','.join(str(m['id']) for m in meetings)})"),
            ("student_id", f"in.({','.join(student_ids)})"),
        ])
        attendees = {str(r["meeting_id"]) for r in rows}

    # One list of everything that can block a slot: (start, end, room, lecturer busy?, students busy?)
    busy = []
    for o in sessions:
        busy.append((parse_ts(o["starts_at"]), parse_ts(o["ends_at"]), str(o["room_id"]) if o.get("room_id") else None,
                     str(o["lecturer_id"]) == lecturer_id, (str(o["intake_id"]), o["group_number"]) in groups))
    for m in meetings:
        busy.append((parse_ts(m["starts_at"]), parse_ts(m["ends_at"]), str(m["room_id"]) if m.get("room_id") else None,
                     str(m["lecturer_id"]) == lecturer_id, str(m["id"]) in attendees))

    candidates = []
    for offset, day in days:
        for minute in range(OPEN_MIN, CLOSE_MIN - moving["duration_minutes"] + 1, STEP_MIN):
            start = datetime.combine(day, datetime.min.time(), tzinfo=MY_TZ) + timedelta(minutes=minute)
            end = start + duration
            if start <= now or start == current_start:
                continue
            clashing = [b for b in busy if b[0] < end + GAP and start < b[1] + GAP]  # 15 minutes either side
            if any(b[3] or b[4] for b in clashing):
                continue  # the lecturer or the students are busy
            taken = {b[2] for b in clashing}
            room = next((r for r in rooms if str(r["id"]) not in taken), None)
            if room is None:
                continue
            candidates.append((abs(offset) * 1000 + abs(minute - wanted_min), {
                "session_date": f"{day:%Y-%m-%d}", "start_time": f"{start:%H:%M}", "end_time": f"{end:%H:%M}",
                "room_id": str(room["id"]), "room_name": room["name"], "building": room.get("building"),
                "capacity": room["capacity"],
            }))
    candidates.sort(key=lambda c: c[0])

    chosen: list[dict] = []
    for _, slot in candidates:  # keep suggestions at least an hour apart on the same day
        def minutes(hhmm: str) -> int:
            return int(hhmm[:2]) * 60 + int(hhmm[3:5])
        if any(c["session_date"] == slot["session_date"] and abs(minutes(c["start_time"]) - minutes(slot["start_time"])) < 60
               for c in chosen):
            continue
        chosen.append(slot)
        if len(chosen) == limit:
            break
    return chosen


# One move at a time per backend process, so two requests cannot both pass the checks for the same room.
# (With several workers, or another program writing bookings, a clash can still slip through.)
RESCHEDULE_LOCK = asyncio.Lock()


def span_text(start: str, end: str) -> str:
    return f"{parse_ts(start).astimezone(MY_TZ):%H:%M}–{parse_ts(end).astimezone(MY_TZ):%H:%M}"


def refuse(status: int, message: str, conflicts: list | None = None) -> HTTPException:
    return HTTPException(status, {"message": message, "conflicts": conflicts or []})


async def auth_user_id(db: "Supabase", session: SessionUser, lecturer_id: str) -> str:
    """The auth.users id to record in schedule_changes.changed_by (the person who made the change)."""
    for name in ("user_id", "auth_user_id"):
        value = getattr(session, name, None)
        if value:
            return str(value)
    rows = await db.get("lecturers", [("select", "auth_user_id"), ("id", f"eq.{lecturer_id}")])  # the lecturer's own login
    if rows and rows[0].get("auth_user_id"):
        return str(rows[0]["auth_user_id"])
    raise refuse(409, "This lecturer's account is not linked to a login yet, so the change cannot be recorded.")


async def find_conflicts(db: "Supabase", moving: dict, lecturer_id: str, room_id: str,
                         new_start: datetime, new_end: datetime) -> list[dict]:
    """Raises 422 if the time or room breaks a rule; otherwise returns every clash (empty = free)."""
    local_start, local_end = new_start.astimezone(MY_TZ), new_end.astimezone(MY_TZ)
    if local_start.isoweekday() not in WORK_ISO_DAYS:
        raise refuse(422, "Classes run Monday to Friday only.")
    start_min = local_start.hour * 60 + local_start.minute
    end_min = local_end.hour * 60 + local_end.minute
    if start_min < OPEN_MIN or local_end.date() != local_start.date() or end_min > CLOSE_MIN:
        raise refuse(422, f"Classes must start at {OPEN_MIN // 60:02d}:00 or later and finish by {CLOSE_MIN // 60:02d}:00. "
                          f"This one would run {local_start:%H:%M} – {local_end:%H:%M}.")

    rooms = await db.get("rooms", [("select", "id,name,capacity,room_type,is_active"), ("id", f"eq.{room_id}")])
    if not rooms or not rooms[0].get("is_active"):
        raise refuse(422, "That room is not available.")
    room = rooms[0]
    kinds = allowed_room_types(moving["course_type"])
    if room["room_type"] not in kinds:
        raise refuse(422, f"A {moving['course_type']} class cannot use {room['name']} (a {room['room_type']} room). "
                          f"Use: {' or '.join(kinds)}.")
    student_ids, groups = await load_students(db, moving)
    if student_ids and room["capacity"] < len(student_ids):
        raise refuse(422, f"{room['name']} seats {room['capacity']}, but this group has {len(student_ids)} students.")
    if new_start == parse_ts(moving["starts_at"]) and str(moving.get("room_id")) == room_id:
        raise refuse(422, "Nothing has changed. Pick a different time or room.")

    # Anything that overlaps the new time, or is within 15 minutes of it on either side.
    conflicts: list[dict] = []
    window = [("starts_at", f"lt.{utc_text(new_end + GAP)}"), ("ends_at", f"gt.{utc_text(new_start - GAP)}")]

    def clash(kind: str, subject_overlap: str, subject_near: str, label: str, starts: str, ends: str) -> None:
        overlaps = parse_ts(starts) < new_end and new_start < parse_ts(ends)
        text = subject_overlap if overlaps else subject_near
        conflicts.append({"type": kind, "message": text.format(label=label, when=span_text(starts, ends))})

    others = await db.get("class_session_details", [
        ("select", "id,room_id,lecturer_id,intake_id,group_number,course_code,course_type,starts_at,ends_at"),
        ("status", f"in.({','.join(ACTIVE_STATUSES)})"),
        ("id", f"neq.{moving['id']}"),
        *window,
    ])
    others = await without_removed(db, others)
    for other in others:
        label = f"{other['course_code']} {other['course_type']}"
        args = (label, other["starts_at"], other["ends_at"])
        if other.get("room_id") and str(other["room_id"]) == room_id:
            clash("room", f"{room['name']} is already booked for {{label}} ({{when}}).",
                  f"{room['name']} is used for {{label}} ({{when}}); leave at least 15 minutes between classes.", *args)
        if str(other["lecturer_id"]) == lecturer_id:
            clash("lecturer", "You already have {label} ({when}).",
                  "You have {label} ({when}); leave at least 15 minutes between classes.", *args)
        if (str(other["intake_id"]), other["group_number"]) in groups:
            clash("student", "Students in this group already have {label} ({when}).",
                  "Students in this group have {label} ({when}); leave at least 15 minutes between classes.", *args)

    meetings = await db.get("meeting_sessions", [
        ("select", "id,room_id,lecturer_id,starts_at,ends_at"), ("status", "eq.scheduled"), *window,
    ])
    attendees: set[str] = set()
    if meetings and student_ids:
        rows = await db.get("meeting_students", [
            ("select", "meeting_id,student_id"),
            ("meeting_id", f"in.({','.join(str(m['id']) for m in meetings)})"),
            ("student_id", f"in.({','.join(student_ids)})"),
        ])
        attendees = {str(r["meeting_id"]) for r in rows}
    for meeting in meetings:
        args = ("a meeting", meeting["starts_at"], meeting["ends_at"])
        if meeting.get("room_id") and str(meeting["room_id"]) == room_id:
            clash("room", f"{room['name']} is already booked for {{label}} ({{when}}).",
                  f"{room['name']} is used for {{label}} ({{when}}); leave at least 15 minutes between classes.", *args)
        if str(meeting["lecturer_id"]) == lecturer_id:
            clash("lecturer", "You already have {label} ({when}).",
                  "You have {label} ({when}); leave at least 15 minutes between classes.", *args)
        if str(meeting["id"]) in attendees:
            clash("student", "Some students in this group are in {label} ({when}).",
                  "Some students in this group have {label} ({when}); leave at least 15 minutes between classes.", *args)
    return conflicts


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

            data = await without_removed(db, await db.get("class_session_details", query_params))

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
                "required_room_type": allowed_room_types(s["course_type"])[0],
                "allowed_room_types": list(allowed_room_types(s["course_type"])),
                "status": s["status"],
                "moved": s["status"] == "rescheduled",
                "can_reschedule": s["status"] in ACTIVE_STATUSES and starts_dt > now_utc.astimezone(MY_TZ)
            })
            return results
        except HTTPException:
            raise  # keep the real status (422, 503...) instead of turning it into a 500 below
        except Exception as e:
            # 这一行会直接把错误细节返回给前端
            import traceback
            traceback.print_exc()
            raise HTTPException(500, detail=str(e))

    @router.get("/lecturers/{lecturer_id}/sessions/{session_id}/suggestions", response_model=List[dict])
    async def get_suggestions(
        lecturer_id: str,
        session_id: str,
        request: Request,
        date_: str = Query(..., alias="date"),
        time: str = Query(...),
        flex_days: int = Query(1, ge=0, le=7),
        limit: int = Query(6, ge=1, le=20),
        session: SessionUser = Depends(LECTURER_OR_ADMIN),
    ):
        """Free times close to the date and time the lecturer asked for (see suggest_slots)."""
        check_own_lecturer(session, lecturer_id)
        try:
            wanted_day = date.fromisoformat(date_)
            wanted_min = int(time[:2]) * 60 + int(time[3:5])
            if len(time) != 5 or time[2] != ":" or not 0 <= wanted_min < 24 * 60:
                raise ValueError
        except ValueError:
            raise HTTPException(422, {"message": "Choose a valid date and time.", "conflicts": []})
        db = Supabase(settings, request.app.state.http_client)
        moving = await get_own_session(db, lecturer_id, session_id)
        return await suggest_slots(db, moving, lecturer_id, wanted_day, wanted_min, flex_days, limit)

    @router.patch("/lecturers/{lecturer_id}/sessions/{session_id}")
    async def reschedule_session(lecturer_id: str, session_id: str, payload: RescheduleRequest, request: Request,
                                 session: SessionUser = Depends(LECTURER_OR_ADMIN)):
        check_own_lecturer(session, lecturer_id)
        db = Supabase(settings, request.app.state.http_client)
        try:
            new_start = datetime.combine(date.fromisoformat(payload.session_date),
                                         datetime.strptime(payload.start_time, "%H:%M").time(), tzinfo=MY_TZ)
        except ValueError:
            raise refuse(422, "Choose a valid date and time.")

        async with RESCHEDULE_LOCK:  # check, move and log as one step (within this process)
            moving = await get_own_session(db, lecturer_id, session_id)  # exists, is theirs, not cancelled
            now = datetime.now(timezone.utc)
            if parse_ts(moving["starts_at"]) <= now:
                raise refuse(409, "Classes that have already started cannot be rescheduled.")
            if new_start <= now:
                raise refuse(409, "Choose a start time in the future.")
            new_end = new_start + timedelta(minutes=moving["duration_minutes"])

            conflicts = await find_conflicts(db, moving, lecturer_id, payload.room_id, new_start, new_end)
            if conflicts:
                raise refuse(409, "That slot clashes with another booking.", conflicts)

            changed_by = await auth_user_id(db, session, lecturer_id)
            old_values = {"starts_at": moving.get("starts_at"), "room_id": moving.get("room_id"), "status": moving.get("status")}
            new_values = {"starts_at": new_start.isoformat(), "room_id": payload.room_id, "status": "rescheduled"}
            session_url = f"{db.url}/rest/v1/class_sessions?id=eq.{session_id}"
            log_row = {
                "class_session_id": session_id, "changed_by": changed_by, "action": "reschedule",
                "reason": payload.reason, "old_values": old_values, "new_values": new_values,
            }

            # 1) move the class and mark it rescheduled
            try:
                res = await db.client.patch(session_url, headers=db.headers, json=new_values)
            except Exception as e:
                raise HTTPException(500, f"Failed to update: {str(e)}")
            if res.status_code not in [200, 204]:
                print("Supabase Error:", res.text)
                raise HTTPException(500, f"Failed to update session ({res.text[:300]})")

            # 2) write the history row; if that fails put the class back, so the timetable and the log agree
            try:
                log = await db.client.post(f"{db.url}/rest/v1/schedule_changes", headers=db.headers, json=log_row)
                if log.status_code not in [200, 201, 204]:
                    print("Supabase Error:", log.text)
                    raise RuntimeError(f"log insert returned {log.status_code}: {log.text[:300]}")
            except Exception as e:
                try:
                    await db.client.patch(session_url, headers=db.headers, json=old_values)
                except Exception as undo_error:
                    print("Could not undo the reschedule:", undo_error)
                raise HTTPException(500, f"Failed to log the change, so nothing was changed: {str(e)}")

        return {"status": "ok"}

    return router
