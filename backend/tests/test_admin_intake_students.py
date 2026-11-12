import json
import re

import httpx
from fastapi.testclient import TestClient

from backend.app.admin import temporary_password
from backend.app.config import load_settings
from backend.app.main import create_app

ADMIN_ID = '00000000-0000-4000-8000-000000000001'
INTAKE_ID = '00000000-0000-4000-8000-000000000010'
STUDENT_ID = '00000000-0000-4000-8000-000000000020'
NEW_ID = '00000000-0000-4000-8000-000000000021'
AUTH_ID = '00000000-0000-4000-8000-000000000030'
HEADERS = {'Authorization': 'Bearer admin-token'}


def make_client(monkeypatch, routes):
    """A test app whose Supabase calls go to `routes(request)` after the admin check."""
    settings = load_settings()
    settings.supabase.url_env = 'TEST_ADMIN_URL'
    settings.supabase.key_env = 'TEST_ADMIN_KEY'
    monkeypatch.setenv('TEST_ADMIN_URL', 'http://test-supabase')
    monkeypatch.setenv('TEST_ADMIN_KEY', 'test-key')
    calls = []

    def handler(request):
        if request.url.path == '/auth/v1/user':
            return httpx.Response(200, json={'id': ADMIN_ID})
        if request.url.path == '/rest/v1/admins':
            return httpx.Response(200, json=[{'id': ADMIN_ID}])
        calls.append(request)
        return routes(request)

    app = create_app(settings)
    client = TestClient(app)
    client.__enter__()
    app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client, calls


def body(request):
    return json.loads(request.content) if request.content else None


def test_lists_intake_students_with_group_numbers(monkeypatch):
    def routes(request):
        assert request.url.path == '/rest/v1/student_intakes'
        assert request.url.params['intake_id'] == f'eq.{INTAKE_ID}'
        if request.url.params['offset'] != '0':
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=[
            {'group_number': 2, 'students': {'id': NEW_ID, 'student_code': 'S2', 'full_name': 'B', 'age': None, 'auth_user_id': 'x'}},
            {'group_number': 1, 'students': {'id': STUDENT_ID, 'student_code': 'S1', 'full_name': 'A', 'age': 20}},
        ])

    client, _ = make_client(monkeypatch, routes)
    response = client.get(f'/api/admin/intakes/{INTAKE_ID}/students', headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == [
        {'id': STUDENT_ID, 'student_code': 'S1', 'full_name': 'A', 'age': 20, 'group_number': 1},
        {'id': NEW_ID, 'student_code': 'S2', 'full_name': 'B', 'age': None, 'group_number': 2},
    ]
    assert client.get(f'/api/admin/intakes/{INTAKE_ID}/students').status_code == 401


def auth_admin(request):
    """Supabase Auth admin API stand-in: create returns a new user id, delete succeeds."""
    if request.method == 'POST' and request.url.path == '/auth/v1/admin/users':
        return httpx.Response(200, json={'id': AUTH_ID, 'email': body(request)['email']})
    if request.method == 'DELETE' and request.url.path == f'/auth/v1/admin/users/{AUTH_ID}':
        return httpx.Response(200, json={})
    return None


def test_adding_a_new_student_creates_a_login_the_record_and_membership(monkeypatch):
    def routes(request):
        if (reply := auth_admin(request)) is not None:
            return reply
        if request.method == 'GET' and request.url.path == '/rest/v1/students':
            return httpx.Response(200, json=[])
        if request.method == 'POST' and request.url.path == '/rest/v1/students':
            return httpx.Response(201, json=[{'id': NEW_ID, **body(request)}])
        if request.method == 'POST' and request.url.path == '/rest/v1/student_intakes':
            return httpx.Response(201, json=[body(request)])
        raise AssertionError(request.url)

    client, calls = make_client(monkeypatch, routes)
    payload = {'student_code': 'TP012345', 'full_name': 'New Student', 'age': None, 'group_number': 2, 'email': ' New.Student@Example.com '}
    response = client.post(f'/api/admin/intakes/{INTAKE_ID}/students', headers=HEADERS, json=payload)
    assert response.status_code == 200
    result = response.json()
    assert result['existing'] is False and result['email'] == 'new.student@example.com'
    assert re.fullmatch(r'TP012345\d{4}', result['temporary_password'])
    assert response.headers['cache-control'] == 'no-store'
    assert [(c.method, c.url.path) for c in calls] == [
        ('GET', '/rest/v1/students'), ('POST', '/auth/v1/admin/users'), ('POST', '/rest/v1/students'), ('POST', '/rest/v1/student_intakes')]
    created = calls[1]
    assert body(created) == {'email': 'new.student@example.com', 'password': result['temporary_password'], 'email_confirm': True,
                             'app_metadata': {'must_change_password': True}}
    assert created.headers['apikey'] == 'test-key' and 'authorization' not in created.headers  # sb_secret-style key: apikey only
    assert body(calls[2]) == {'student_code': 'TP012345', 'full_name': 'New Student', 'auth_user_id': AUTH_ID}
    assert body(calls[3]) == {'student_id': NEW_ID, 'intake_id': INTAKE_ID, 'group_number': 2}


def test_new_student_needs_a_valid_email(monkeypatch):
    def routes(request):
        if request.method == 'GET' and request.url.path == '/rest/v1/students':
            return httpx.Response(200, json=[])
        raise AssertionError(request.url)

    client, calls = make_client(monkeypatch, routes)
    payload = {'student_code': 'S9', 'full_name': 'New Student', 'group_number': 1}
    assert client.post(f'/api/admin/intakes/{INTAKE_ID}/students', headers=HEADERS, json=payload).status_code == 422
    assert client.post(f'/api/admin/intakes/{INTAKE_ID}/students', headers=HEADERS, json={**payload, 'email': 'not-an-email'}).status_code == 422
    assert not any(c.url.path.startswith('/auth/') for c in calls)


def test_adding_an_existing_code_links_it_and_a_failed_link_undoes_the_record_and_login(monkeypatch):
    state = {'existing': True}

    def routes(request):
        if (reply := auth_admin(request)) is not None:
            return reply
        if request.method == 'GET' and request.url.path == '/rest/v1/students':
            return httpx.Response(200, json=[{'id': STUDENT_ID, 'full_name': 'Old Name'}] if state['existing'] else [])
        if request.method == 'POST' and request.url.path == '/rest/v1/students':
            return httpx.Response(201, json=[{'id': NEW_ID}])
        if request.method == 'POST' and request.url.path == '/rest/v1/student_intakes':
            if state['existing']:
                return httpx.Response(201, json=[body(request)])
            return httpx.Response(400, json={'code': '23514'})  # group above the intake's maximum
        if request.method == 'DELETE' and request.url.path == '/rest/v1/students':
            return httpx.Response(200, json=[{'id': NEW_ID}])
        raise AssertionError(request.url)

    client, calls = make_client(monkeypatch, routes)
    payload = {'student_code': 'S1', 'full_name': 'Typed Name', 'group_number': 1, 'email': 's1@example.com'}
    response = client.post(f'/api/admin/intakes/{INTAKE_ID}/students', headers=HEADERS, json=payload)
    assert response.json() == {'id': STUDENT_ID, 'existing': True, 'full_name': 'Old Name'}
    assert not any(c.method == 'POST' and c.url.path in ('/rest/v1/students', '/auth/v1/admin/users') for c in calls)

    state['existing'] = False
    calls.clear()
    response = client.post(f'/api/admin/intakes/{INTAKE_ID}/students', headers=HEADERS, json={**payload, 'group_number': 9})
    assert response.status_code == 422
    assert [(c.method, c.url.path) for c in calls][-2:] == [('DELETE', '/rest/v1/students'), ('DELETE', f'/auth/v1/admin/users/{AUTH_ID}')]
    assert client.post(f'/api/admin/intakes/{INTAKE_ID}/students', headers=HEADERS, json={**payload, 'group_number': 0}).status_code == 422


def test_duplicate_email_is_a_conflict_and_creates_no_record(monkeypatch):
    def routes(request):
        if request.method == 'POST' and request.url.path == '/auth/v1/admin/users':
            return httpx.Response(422, json={'code': 422, 'error_code': 'email_exists', 'msg': 'already registered'})
        if request.method == 'GET':
            return httpx.Response(200, json=[])
        raise AssertionError(request.url)

    client, calls = make_client(monkeypatch, routes)
    student = {'student_code': 'S9', 'full_name': 'New', 'group_number': 1, 'email': 'taken@example.com'}
    response = client.post(f'/api/admin/intakes/{INTAKE_ID}/students', headers=HEADERS, json=student)
    assert response.status_code == 409 and response.json()['detail'] == 'An account with this email already exists.'
    response = client.post('/api/admin/lecturers', headers=HEADERS, json={'lecturer_code': 'L9', 'full_name': 'New', 'email': 'taken@example.com'})
    assert response.status_code == 409
    assert not any(c.method == 'POST' and c.url.path.startswith('/rest/') for c in calls)


def test_adding_a_lecturer_creates_a_login_and_a_linked_record(monkeypatch):
    state = {'fail_insert': False}

    def routes(request):
        if (reply := auth_admin(request)) is not None:
            return reply
        if request.method == 'GET' and request.url.path == '/rest/v1/lecturers':
            return httpx.Response(200, json=[{'id': NEW_ID}] if request.url.params['lecturer_code'] == 'eq.L1' else [])
        if request.method == 'POST' and request.url.path == '/rest/v1/lecturers':
            if state['fail_insert']:
                return httpx.Response(400, json={'code': '23505'})
            return httpx.Response(201, json=[{'id': NEW_ID, **body(request)}])
        raise AssertionError(request.url)

    client, calls = make_client(monkeypatch, routes)
    lecturer = {'lecturer_code': 'TP000777', 'full_name': 'Dr New', 'email': 'dr.new@example.com'}
    response = client.post('/api/admin/lecturers', headers=HEADERS, json=lecturer)
    assert response.status_code == 200
    result = response.json()
    assert result['id'] == NEW_ID and result['email'] == 'dr.new@example.com'
    assert re.fullmatch(r'TP000777\d{4}', result['temporary_password'])
    assert body(calls[-1]) == {'lecturer_code': 'TP000777', 'full_name': 'Dr New', 'auth_user_id': AUTH_ID}
    assert body(calls[-2])['password'] == result['temporary_password']

    calls.clear()
    assert client.post('/api/admin/lecturers', headers=HEADERS, json={**lecturer, 'lecturer_code': 'L1'}).status_code == 409
    assert not any(c.url.path.startswith('/auth/') for c in calls)  # code checked before any login is made

    state['fail_insert'] = True
    calls.clear()
    assert client.post('/api/admin/lecturers', headers=HEADERS, json=lecturer).status_code == 409
    assert (calls[-1].method, calls[-1].url.path) == ('DELETE', f'/auth/v1/admin/users/{AUTH_ID}')

    assert client.post('/api/admin/lecturers', headers=HEADERS, json={'lecturer_code': 'L2', 'full_name': 'X'}).status_code == 422
    assert client.post('/api/admin/lecturers', json=lecturer).status_code == 401


def test_editing_a_lecturer_still_uses_the_generic_route_without_email(monkeypatch):
    def routes(request):
        return httpx.Response(200, json=[{'id': NEW_ID, **(body(request) or {})}])

    client, calls = make_client(monkeypatch, routes)
    edit = {'lecturer_code': 'L1', 'full_name': 'Renamed'}
    assert client.put(f'/api/admin/lecturers/{NEW_ID}', headers=HEADERS, json=edit).status_code == 200
    assert (calls[-1].method, body(calls[-1])) == ('PATCH', edit)
    assert client.put(f'/api/admin/lecturers/{NEW_ID}', headers=HEADERS, json={**edit, 'email': 'x@example.com'}).status_code == 422


def test_temporary_password_is_code_plus_four_random_digits():
    passwords = {temporary_password('TP012345') for _ in range(50)}
    assert all(re.fullmatch(r'TP012345\d{4}', p) for p in passwords)
    assert len(passwords) > 1


def test_removing_the_last_membership_deletes_an_unlinked_student(monkeypatch):
    state = {'login': None}

    def routes(request):
        path, method = request.url.path, request.method
        if method == 'DELETE' and path == '/rest/v1/student_intakes':
            return httpx.Response(200, json=[{'student_id': STUDENT_ID}])
        if method == 'GET' and path == '/rest/v1/student_intakes':
            return httpx.Response(200, json=[])
        if method == 'GET' and path == '/rest/v1/students':
            return httpx.Response(200, json=[{'auth_user_id': state['login']}])
        if method == 'DELETE' and path == '/rest/v1/students':
            return httpx.Response(200, json=[{'id': STUDENT_ID}])
        raise AssertionError(request.url)

    client, calls = make_client(monkeypatch, routes)
    url = f'/api/admin/intakes/{INTAKE_ID}/students/{STUDENT_ID}'
    assert client.delete(url, headers=HEADERS).json() == {'status': 'ok', 'student_deleted': True}
    state['login'] = 'linked-account'
    calls.clear()
    assert client.delete(url, headers=HEADERS).json() == {'status': 'ok', 'student_deleted': False}
    assert not any(c.method == 'DELETE' and c.url.path == '/rest/v1/students' for c in calls)


def test_editing_updates_the_student_and_group(monkeypatch):
    def routes(request):
        if request.method == 'GET' and request.url.path == '/rest/v1/student_intakes':
            return httpx.Response(200, json=[{'group_number': 1}])
        if request.method == 'PATCH':
            return httpx.Response(200, json=[body(request)])
        raise AssertionError(request.url)

    client, calls = make_client(monkeypatch, routes)
    payload = {'student_code': 'S1', 'full_name': 'Renamed', 'age': 21, 'group_number': 3}
    assert client.put(f'/api/admin/intakes/{INTAKE_ID}/students/{STUDENT_ID}', headers=HEADERS, json=payload).status_code == 200
    patches = [(c.url.path, body(c)) for c in calls if c.method == 'PATCH']
    assert patches == [('/rest/v1/students', {'student_code': 'S1', 'full_name': 'Renamed', 'age': 21}),
                       ('/rest/v1/student_intakes', {'group_number': 3})]


def test_course_type_defaults_to_lecture_and_is_kept_on_edit(monkeypatch):
    def routes(request):
        return httpx.Response(200, json=[{'id': NEW_ID, **(body(request) or {})}])

    client, calls = make_client(monkeypatch, routes)
    course = {'course_code': 'CS101', 'name': 'Intro', 'duration_minutes': 60}
    assert client.post('/api/admin/courses', headers=HEADERS, json=course).status_code == 200
    assert body(calls[-1]) == {**course, 'course_type': 'lecture'}
    assert client.put(f'/api/admin/courses/{NEW_ID}', headers=HEADERS, json=course).status_code == 200
    assert body(calls[-1]) == course
    assert client.post('/api/admin/courses', headers=HEADERS, json={**course, 'course_type': 'lab'}).status_code == 200
    assert body(calls[-1])['course_type'] == 'lab'


def test_intake_list_includes_memberships_and_offerings(monkeypatch):
    def routes(request):
        assert request.url.params['select'] == '*,student_intakes(student_id,group_number),course_offerings(id)'
        return httpx.Response(200, json=[])

    client, _ = make_client(monkeypatch, routes)
    assert client.get('/api/admin/intakes', headers=HEADERS).json() == []
