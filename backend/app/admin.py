import asyncio
from typing import Literal
from datetime import datetime, timedelta
from uuid import UUID

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .auth import get_session
from .config import SupabaseSettings
from .student import Supabase, in_list


class Course(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    course_code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    course_type: Literal['lecture', 'tutorial', 'lab', 'others']
    duration_minutes: int = Field(gt=0, strict=True)


class Profile(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    full_name: str = Field(min_length=1)
    student_code: str | None = None
    lecturer_code: str | None = None
    age: int | None = Field(default=None, ge=0, strict=True)


class Intake(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    intake_code: str = Field(min_length=1)
    max_group: int = Field(ge=1, strict=True)


class Reschedule(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    expected_start: datetime
    expected_room: UUID
    new_start: datetime
    new_room: UUID
    reason: str = Field(min_length=1, max_length=500)


def create_admin_router(settings: SupabaseSettings):
    router = APIRouter(prefix='/api/admin', tags=['admin'])
    tables = {'courses', 'students', 'lecturers', 'admins', 'intakes'}

    async def authorized(request: Request, authorization: str | None):
        """Return (database client, the admin's 'Bearer <token>'), or raise 401/403.

        A logged-in admin (login cookie) is accepted directly. A pasted Supabase
        token in the Authorization header still works as before."""
        token = authorization.removeprefix('Bearer ').strip() if authorization and authorization.startswith('Bearer ') else ''
        if not token:
            session = await get_session(request)
            if session is None:
                raise HTTPException(401, 'Admin sign-in required.')
            if session.role != 'admin':
                raise HTTPException(403, 'Administrator access required.')
            return Supabase(settings, request.app.state.http_client), f'Bearer {request.state.access_token}'
        authorization = f'Bearer {token}'
        db = Supabase(settings, request.app.state.http_client)
        try:
            response = await db.client.get(f'{db.url}/auth/v1/user', headers={**db.headers, 'Authorization': authorization}, timeout=db.timeout)
            if response.status_code != 200:
                raise HTTPException(401, 'Invalid or expired session.')
            user_id = str(UUID(response.json()['id']))
            admins = await db.get('admins', [('select', 'id'), ('auth_user_id', f'eq.{user_id}'), ('limit', '1')])
        except (httpx.RequestError, ValueError, KeyError):
            raise HTTPException(502, 'Could not verify the admin session.')
        if not admins:
            raise HTTPException(403, 'Administrator access required.')
        return db, authorization

    async def read_all(db: Supabase, table: str, params: list[tuple[str, str]]):
        rows = []
        while True:
            page = await db.get(table, params + [('limit', '500'), ('offset', str(len(rows)))])
            if not page:
                return rows
            rows.extend(page)

    @router.get('/timetable/rooms')
    async def timetable_rooms(request: Request, authorization: str | None = Header(default=None)):
        db, _ = await authorized(request, authorization)
        return await read_all(db, 'rooms', [('select', 'id,name,building,room_type,capacity'), ('is_active', 'eq.true'), ('order', 'name,id')])

    async def timetable_rpc(db: Supabase, authorization: str, name: str, body: dict):
        try:
            response = await db.client.post(
                f'{db.url}/rest/v1/rpc/{name}', headers={**db.headers, 'Authorization': authorization},
                json=body, timeout=db.timeout,
            )
        except httpx.RequestError:
            raise HTTPException(502, 'Could not reach Supabase.')
        if response.status_code >= 400:
            try:
                code = response.json().get('code')
            except ValueError:
                code = None
            if code in ('23P01', '40001'):
                raise HTTPException(409, 'The class changed or the room, lecturer or students have a conflict. Refresh and check the schedule.')
            if code == '22023':
                raise HTTPException(400, 'Check the class status, room suitability, capacity and required fields.')
            if code == 'P0002':
                raise HTTPException(404, 'Class not found or already removed.')
            if code in ('PGRST202', '42883'):
                raise HTTPException(503, 'The timetable migration has not been applied to this database.')
            raise HTTPException(502, 'The database could not complete this timetable change.')
        return {'status': 'ok'}

    @router.put('/timetable/{session_id}')
    async def reschedule(session_id: UUID, payload: Reschedule, request: Request, authorization: str | None = Header(default=None)):
        db, authorization = await authorized(request, authorization)
        if payload.expected_start.tzinfo is None or payload.new_start.tzinfo is None:
            raise HTTPException(422, 'Times must include a timezone.')
        return await timetable_rpc(db, authorization, 'admin_reschedule_class', {
            'session_id': str(session_id), 'expected_start': payload.expected_start.isoformat(),
            'expected_room': str(payload.expected_room), 'new_start': payload.new_start.isoformat(),
            'new_room': str(payload.new_room), 'change_reason': payload.reason,
        })

    @router.delete('/timetable/{session_id}')
    async def remove_cancelled(session_id: UUID, request: Request, authorization: str | None = Header(default=None)):
        db, authorization = await authorized(request, authorization)
        return await timetable_rpc(db, authorization, 'admin_remove_cancelled_class', {'session_id': str(session_id)})

    @router.get('/timetable')
    async def timetable(request: Request, start: datetime, end: datetime, authorization: str | None = Header(default=None)):
        db, _ = await authorized(request, authorization)
        if start.tzinfo is None or end.tzinfo is None or end <= start or end - start > timedelta(days=31):
            raise HTTPException(422, 'Choose a valid date range of no more than 31 days with a timezone.')
        sessions = await read_all(db, 'class_session_details', [
            ('select', 'id,starts_at,ends_at,status,group_number,intake_id,course_code,course_name,course_type,room_id,lecturer_id'),
            ('starts_at', f'gte.{start.isoformat()}'), ('starts_at', f'lt.{end.isoformat()}'), ('order', 'starts_at,id'),
        ])
        async def lookup(table, select, ids):
            results = []
            ids = sorted(ids)
            for offset in range(0, len(ids), 100):
                results.extend(await read_all(db, table, [('select', select), ('id', in_list(ids[offset:offset + 100])), ('order', 'id')]))
            return results
        rooms, lecturers, intakes = await asyncio.gather(
            lookup('rooms', 'id,name,building', {s['room_id'] for s in sessions if s.get('room_id')}),
            lookup('lecturers', 'id,full_name', {s['lecturer_id'] for s in sessions if s.get('lecturer_id')}),
            lookup('intakes', 'id,intake_code', {s['intake_id'] for s in sessions if s.get('intake_id')}),
        )
        maps = [{row['id']: row for row in items} for items in (rooms, lecturers, intakes)]
        return [{**s, 'room': maps[0].get(s.get('room_id')), 'lecturer': maps[1].get(s.get('lecturer_id')), 'intake': maps[2].get(s.get('intake_id'))} for s in sessions]

    @router.api_route('/{table}', methods=['GET', 'POST'])
    @router.api_route('/{table}/{item_id}', methods=['PUT', 'DELETE'])
    async def manage(table: str, request: Request, item_id: UUID | None = None, authorization: str | None = Header(default=None)):
        if table not in tables:
            raise HTTPException(404, 'Unknown resource.')
        db, _ = await authorized(request, authorization)
        if request.method == 'GET':
            select = '*,course_offerings(intakes(intake_code))' if table == 'courses' else '*'
            return await read_all(db, table, [('select', select), ('order', 'id')])
        payload = None
        if request.method != 'DELETE':
            try:
                data = await request.json()
                if table == 'courses':
                    payload = Course.model_validate(data).model_dump()
                elif table == 'intakes':
                    payload = Intake.model_validate(data).model_dump()
                else:
                    profile = Profile.model_validate(data)
                    allowed = {'students': {'full_name', 'student_code', 'age'}, 'lecturers': {'full_name', 'lecturer_code'}, 'admins': {'full_name'}}[table]
                    if set(data) - allowed or (table != 'admins' and not getattr(profile, table[:-1] + '_code')):
                        raise ValueError('Required profile code missing or unexpected field.')
                    payload = profile.model_dump(include=allowed)
            except (ValueError, TypeError):
                raise HTTPException(422, 'Check the required fields and values.')
        params = {'id': f'eq.{item_id}'} if item_id else {}
        try:
            response = await db.client.request(request.method if request.method != 'PUT' else 'PATCH', f'{db.url}/rest/v1/{table}', params=params, json=payload, headers={**db.headers, 'Prefer': 'return=representation'}, timeout=db.timeout)
        except httpx.RequestError:
            raise HTTPException(502, 'Could not reach Supabase.')
        if response.status_code >= 400:
            try:
                code = response.json().get('code')
            except ValueError:
                code = None
            if code == '23503':
                raise HTTPException(409, 'This record is in use and cannot be deleted.')
            if code == '23505':
                raise HTTPException(409, 'A record with these details already exists.')
            raise HTTPException(400, 'The database rejected this change. Check the values and related records.')
        rows = response.json()
        if item_id and not rows:
            raise HTTPException(404, 'Record not found.')
        return rows
    return router
