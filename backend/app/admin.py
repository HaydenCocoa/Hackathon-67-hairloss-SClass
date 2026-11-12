import asyncio
import secrets
from typing import Literal
from datetime import datetime, timedelta
from uuid import UUID

import httpx
from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from .auth import PASSWORD_FLAG, get_session, password_change_required
from .config import SupabaseSettings
from .student import Supabase, in_list


class Course(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    course_code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    # Not shown on the admin page since 12 Nov 2026: new courses default to 'lecture'
    # and an edit without it keeps the stored type (the scheduler's room policy uses it).
    course_type: Literal['lecture', 'tutorial', 'lab', 'others'] | None = None
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


class IntakeStudent(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    student_code: str = Field(min_length=1)
    full_name: str = Field(min_length=1)
    age: int | None = Field(default=None, ge=0, strict=True)
    group_number: int = Field(ge=1, strict=True)


EMAIL_PATTERN = r'^[^@\s]+@[^@\s]+\.[^@\s]+$'


class NewIntakeStudent(IntakeStudent):
    # Needed only when the student code is new: that student gets a Supabase Auth login.
    email: str | None = Field(default=None, max_length=254, pattern=EMAIL_PATTERN)


class NewLecturer(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    lecturer_code: str = Field(min_length=1)
    full_name: str = Field(min_length=1)
    email: str = Field(max_length=254, pattern=EMAIL_PATTERN)


def temporary_password(code: str) -> str:
    """The user's code (TP number) followed by 4 random digits from a secure source."""
    return f'{code}{secrets.randbelow(10_000):04d}'


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
            if session.must_change_password:
                raise password_change_required()
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

    async def write(db: Supabase, method: str, table: str, params: dict, payload=None):
        """One PostgREST write with the admin page's error messages. Returns the changed rows."""
        try:
            response = await db.client.request(method, f'{db.url}/rest/v1/{table}', params=params, json=payload,
                                               headers={**db.headers, 'Prefer': 'return=representation'}, timeout=db.timeout)
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
            if code == '23514':
                raise HTTPException(422, 'The group number is higher than this intake allows.')
            raise HTTPException(400, 'The database rejected this change. Check the values and related records.')
        return response.json()

    # Logins are created with the Supabase Auth admin API using the server-only key.
    # Supabase Auth hashes the password with bcrypt (per-user salt) and stores only the
    # hash; this backend sends it once over HTTPS and never hashes, stores or logs it.
    async def create_login(db: Supabase, email: str, password: str) -> str:
        """Create a confirmed email/password user and return its auth user id."""
        try:
            response = await db.client.post(f'{db.url}/auth/v1/admin/users', headers={**db.headers, 'Content-Type': 'application/json'},
                                            json={'email': email, 'password': password, 'email_confirm': True,
                                                  # Forces a password change at first login (see auth.py).
                                                  # app_metadata cannot be edited by the user, unlike user_metadata.
                                                  'app_metadata': {PASSWORD_FLAG: True}}, timeout=db.timeout)
        except httpx.RequestError:
            raise HTTPException(502, 'Could not reach Supabase Auth.')
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.status_code >= 400:
            code = data.get('error_code') if isinstance(data, dict) else None
            if code in ('email_exists', 'user_already_exists'):
                raise HTTPException(409, 'An account with this email already exists.')
            if code == 'weak_password':
                raise HTTPException(422, "The temporary password does not meet this project's password rules in Supabase Auth.")
            if code in ('email_address_invalid', 'validation_failed'):
                raise HTTPException(422, 'Supabase Auth rejected this email address.')
            if response.status_code in (401, 403):
                raise HTTPException(502, 'The server key cannot create logins. SUPABASE_KEY must be the secret (service role) key.')
            raise HTTPException(502, 'Supabase Auth could not create the login.')
        try:
            return str(UUID(str(data['id'])))
        except (KeyError, TypeError, ValueError):
            raise HTTPException(502, 'Supabase Auth returned an unexpected response.')

    async def delete_login(db: Supabase, auth_user_id: str) -> None:
        """Best-effort undo of create_login when a later step fails."""
        try:
            await db.client.delete(f'{db.url}/auth/v1/admin/users/{auth_user_id}', headers=db.headers, timeout=db.timeout)
        except httpx.RequestError:
            pass

    def credentials(response: Response, email: str, password: str) -> dict:
        response.headers['Cache-Control'] = 'no-store'  # the temporary password is shown once
        return {'email': email, 'temporary_password': password}

    def student_row(membership: dict) -> dict:
        student = membership.get('students') or {}
        return {'id': student.get('id'), 'student_code': student.get('student_code'), 'full_name': student.get('full_name'),
                'age': student.get('age'), 'group_number': membership.get('group_number')}

    # Students are managed per intake (Admin > Intakes > Students). Membership rows in
    # student_intakes carry the group number; a student may belong to several intakes.
    @router.get('/intakes/{intake_id}/students')
    async def intake_students(intake_id: UUID, request: Request, authorization: str | None = Header(default=None)):
        db, _ = await authorized(request, authorization)
        rows = await read_all(db, 'student_intakes', [('select', 'group_number,students(*)'), ('intake_id', f'eq.{intake_id}'),
                                                      ('order', 'group_number,student_id')])
        return sorted((student_row(row) for row in rows), key=lambda r: (r['group_number'] or 0, r['student_code'] or ''))

    @router.post('/intakes/{intake_id}/students')
    async def add_intake_student(intake_id: UUID, payload: NewIntakeStudent, request: Request, response: Response,
                                 authorization: str | None = Header(default=None)):
        """Add a student to this intake. An existing student code is linked as it is
        (name, age and login unchanged). Otherwise a Supabase Auth login (email plus a
        temporary password) and a new student record linked to it are created."""
        db, _ = await authorized(request, authorization)
        existing = await db.get('students', [('select', 'id,full_name'), ('student_code', f'eq.{payload.student_code}'), ('limit', '1')])
        if existing:
            student_id = existing[0]['id']
            try:
                await write(db, 'POST', 'student_intakes', {}, {'student_id': student_id, 'intake_id': str(intake_id), 'group_number': payload.group_number})
            except HTTPException as error:
                if error.status_code == 409:
                    raise HTTPException(409, 'This student is already in this intake.')
                raise
            return {'id': student_id, 'existing': True, 'full_name': existing[0]['full_name']}
        if not payload.email:
            raise HTTPException(422, "Enter the new student's email address.")
        email, password = payload.email.lower(), temporary_password(payload.student_code)
        auth_user_id = await create_login(db, email, password)
        student_id = None
        try:
            body = payload.model_dump(include={'student_code', 'full_name'} | ({'age'} if payload.age is not None else set()))
            student_id = (await write(db, 'POST', 'students', {}, {**body, 'auth_user_id': auth_user_id}))[0]['id']
            await write(db, 'POST', 'student_intakes', {}, {'student_id': student_id, 'intake_id': str(intake_id), 'group_number': payload.group_number})
        except HTTPException:
            # Separate writes, not one transaction: undo in reverse so nothing half-made is left.
            if student_id:
                try:
                    await write(db, 'DELETE', 'students', {'id': f'eq.{student_id}'})
                except HTTPException:
                    pass
            await delete_login(db, auth_user_id)
            raise
        return {'id': student_id, 'existing': False, 'full_name': payload.full_name, **credentials(response, email, password)}

    @router.put('/intakes/{intake_id}/students/{student_id}')
    async def edit_intake_student(intake_id: UUID, student_id: UUID, payload: IntakeStudent, request: Request, authorization: str | None = Header(default=None)):
        db, _ = await authorized(request, authorization)
        membership = {'student_id': f'eq.{student_id}', 'intake_id': f'eq.{intake_id}'}
        if not await db.get('student_intakes', [('select', 'group_number'), *membership.items()]):
            raise HTTPException(404, 'This student is not in this intake.')
        await write(db, 'PATCH', 'students', {'id': f'eq.{student_id}'}, payload.model_dump(include={'student_code', 'full_name', 'age'}))
        await write(db, 'PATCH', 'student_intakes', membership, {'group_number': payload.group_number})
        return {'status': 'ok'}

    @router.delete('/intakes/{intake_id}/students/{student_id}')
    async def remove_intake_student(intake_id: UUID, student_id: UUID, request: Request, authorization: str | None = Header(default=None)):
        """Remove the student from this intake. The student record is also deleted when they
        belong to no other intake, have no login, and nothing else (such as a meeting) uses it."""
        db, _ = await authorized(request, authorization)
        removed = await write(db, 'DELETE', 'student_intakes', {'student_id': f'eq.{student_id}', 'intake_id': f'eq.{intake_id}'})
        if not removed:
            raise HTTPException(404, 'This student is not in this intake.')
        deleted = False
        if not await db.get('student_intakes', [('select', 'intake_id'), ('student_id', f'eq.{student_id}'), ('limit', '1')]):
            student = await db.get('students', [('select', 'auth_user_id'), ('id', f'eq.{student_id}')])
            if student and not student[0].get('auth_user_id'):
                try:
                    deleted = bool(await write(db, 'DELETE', 'students', {'id': f'eq.{student_id}'}))
                except HTTPException:
                    deleted = False  # still referenced elsewhere; keep the record
        return {'status': 'ok', 'student_deleted': deleted}

    @router.post('/lecturers')
    async def add_lecturer(payload: NewLecturer, request: Request, response: Response, authorization: str | None = Header(default=None)):
        """Create a lecturer with a Supabase Auth login (email plus a temporary password).
        Registered before the generic route; edits and deletes still use the generic route."""
        db, _ = await authorized(request, authorization)
        if await db.get('lecturers', [('select', 'id'), ('lecturer_code', f'eq.{payload.lecturer_code}'), ('limit', '1')]):
            raise HTTPException(409, 'A lecturer with this code already exists.')
        email, password = payload.email.lower(), temporary_password(payload.lecturer_code)
        auth_user_id = await create_login(db, email, password)
        try:
            rows = await write(db, 'POST', 'lecturers', {}, {'lecturer_code': payload.lecturer_code, 'full_name': payload.full_name,
                                                              'auth_user_id': auth_user_id})
        except HTTPException:
            await delete_login(db, auth_user_id)
            raise
        return {**rows[0], **credentials(response, email, password)}

    @router.api_route('/{table}', methods=['GET', 'POST'])
    @router.api_route('/{table}/{item_id}', methods=['PUT', 'DELETE'])
    async def manage(table: str, request: Request, item_id: UUID | None = None, authorization: str | None = Header(default=None)):
        if table not in tables:
            raise HTTPException(404, 'Unknown resource.')
        db, _ = await authorized(request, authorization)
        if request.method == 'GET':
            select = {'courses': '*,course_offerings(intakes(intake_code))',
                      'intakes': '*,student_intakes(student_id,group_number),course_offerings(id)'}.get(table, '*')
            return await read_all(db, table, [('select', select), ('order', 'id')])
        payload = None
        if request.method != 'DELETE':
            try:
                data = await request.json()
                if table == 'courses':
                    payload = Course.model_validate(data).model_dump(exclude_none=True)
                    if request.method == 'POST':
                        payload.setdefault('course_type', 'lecture')
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
