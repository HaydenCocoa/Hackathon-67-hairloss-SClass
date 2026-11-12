"""Forced password change after an admin-created temporary password, against a mock
Supabase Auth (no hosted project). The flag lives in Supabase app_metadata."""

import json
from itertools import count

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app.auth import ACCESS_COOKIE
from backend.app.config import load_settings
from backend.app.main import create_app

BASE = 'http://127.0.0.1:8000'
TEMP = 'TP0000010042'
STUDENT_ID = '00000000-0000-4000-8000-000000000003'
LECTURER_ID = '00000000-0000-4000-8000-000000000002'


@pytest.fixture
def world(monkeypatch, tmp_path):
    users = {  # email -> Supabase user
        'new@example.test': {'id': STUDENT_ID, 'email': 'new@example.test', 'password': TEMP, 'app_metadata': {'provider': 'email', 'must_change_password': True}},
        'old@example.test': {'id': LECTURER_ID, 'email': 'old@example.test', 'password': 'long-standing-pass', 'app_metadata': {'provider': 'email'}},
    }
    rows = {'students': [{'id': 's1', 'full_name': 'New Student', 'student_code': 'TP000001', 'auth_user_id': STUDENT_ID}],
            'lecturers': [{'id': 'l1', 'full_name': 'Old Lecturer', 'lecturer_code': 'L1', 'auth_user_id': LECTURER_ID}],
            'admins': []}
    state = {'tokens': {}, 'calls': [], 'n': count(1), 'fail_flag': False}

    def public(user):
        return {k: v for k, v in user.items() if k != 'password'}

    def by_token(request):
        return state['tokens'].get(request.headers.get('authorization', '').removeprefix('Bearer '))

    def handler(request):
        path, method = request.url.path, request.method
        body = json.loads(request.content) if request.content else {}
        state['calls'].append((method, path, dict(request.url.params), body))
        if path == '/auth/v1/token':
            user = users.get(body.get('email'))
            if not user or user['password'] != body.get('password'):
                return httpx.Response(400, json={'error_code': 'invalid_credentials'})
            token = f"access-{next(state['n'])}"
            state['tokens'][token] = user
            return httpx.Response(200, json={'access_token': token, 'refresh_token': 'r-' + token, 'expires_in': 3600, 'user': public(user)})
        if path == '/auth/v1/user' and method == 'GET':
            user = by_token(request)
            return httpx.Response(200, json=public(user)) if user else httpx.Response(401, json={})
        if path == '/auth/v1/user' and method == 'PUT':
            user = by_token(request)
            if not user:
                return httpx.Response(401, json={})
            if body['password'] == user['password']:
                return httpx.Response(422, json={'error_code': 'same_password'})
            if body['password'] == 'password1234':
                return httpx.Response(422, json={'error_code': 'weak_password', 'weak_password': {'reasons': ['pwned']}})
            user['password'] = body['password']
            return httpx.Response(200, json=public(user))
        if path.startswith('/auth/v1/admin/users/') and method == 'PUT':
            if state['fail_flag']:
                return httpx.Response(500, json={})
            user = next(u for u in users.values() if u['id'] == path.rsplit('/', 1)[1])
            user['app_metadata'] = {**user['app_metadata'], **body['app_metadata']}
            return httpx.Response(200, json=public(user))
        if path == '/auth/v1/logout':
            state['tokens'].pop(request.headers.get('authorization', '').removeprefix('Bearer '), None)
            return httpx.Response(204)
        if path.startswith('/rest/v1/'):
            table = path.removeprefix('/rest/v1/')
            wanted = request.url.params.get('auth_user_id', '').removeprefix('eq.')
            return httpx.Response(200, json=[r for r in rows.get(table, []) if r.get('auth_user_id') == wanted])
        raise AssertionError(f'{method} {path}')

    settings = load_settings()
    settings.supabase.url_env, settings.supabase.key_env = 'PW_TEST_URL', 'PW_TEST_KEY'
    monkeypatch.setenv('PW_TEST_URL', 'http://supabase.test')
    monkeypatch.setenv('PW_TEST_KEY', 'sb_secret_pw_test')
    (tmp_path / 'index.html').write_text('<div id="app"></div>')
    app = create_app(settings, tmp_path)
    client = TestClient(app, base_url=BASE, client=('127.0.0.1', 51000), follow_redirects=False)
    client.__enter__()
    app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    yield client, users, state
    client.__exit__(None, None, None)


def login(client, email, password):
    return client.post('/api/auth/login', json={'email': email, 'password': password})


def change(client, current, new):
    return client.post('/api/auth/change-password', json={'current_password': current, 'new_password': new})


def test_a_temporary_password_only_opens_the_change_password_page(world):
    client, _, _ = world
    response = login(client, 'new@example.test', TEMP)
    assert response.status_code == 200
    assert response.json()['must_change_password'] is True and response.json()['home'] == '/change-password'
    assert client.get('/api/auth/me').json()['must_change_password'] is True
    blocked = client.get('/api/health/database')
    assert blocked.status_code == 403 and blocked.json()['detail']['code'] == 'PASSWORD_CHANGE_REQUIRED'
    assert client.get('/api/student/TP000001').status_code == 403
    assert client.get('/student').headers['location'] == '/change-password'
    assert client.get('/').headers['location'] == '/change-password'
    assert client.get('/login').headers['location'] == '/change-password'
    assert client.get('/change-password').status_code == 200


def test_changing_the_password_clears_the_flag_and_renews_the_session(world):
    client, users, state = world
    login(client, 'new@example.test', TEMP)
    old_access = client.cookies.get(ACCESS_COOKIE)

    wrong = change(client, 'not-it', 'a-new-password')
    assert wrong.status_code == 400 and wrong.json()['detail']['code'] == 'WRONG_PASSWORD'
    assert change(client, TEMP, TEMP).json()['detail']['code'] == 'SAME_PASSWORD'
    assert change(client, TEMP, 'short').status_code == 422
    assert change(client, TEMP, 'x' * 73).status_code == 422
    assert users['new@example.test']['app_metadata']['must_change_password'] is True

    response = change(client, TEMP, 'a-new-password')
    assert response.status_code == 200, response.text
    assert response.json()['must_change_password'] is False and response.json()['home'] == '/student'
    assert response.headers['cache-control'] == 'no-store'
    assert 'a-new-password' not in response.text and TEMP not in response.text
    assert users['new@example.test']['password'] == 'a-new-password'
    assert users['new@example.test']['app_metadata'] == {'provider': 'email', 'must_change_password': False}
    # The old session is revoked on its own (scope=local); the cookies now hold the fresh one.
    logout = [c for c in state['calls'] if c[1] == '/auth/v1/logout']
    assert logout and logout[-1][2] == {'scope': 'local'} and old_access not in state['tokens']
    assert client.cookies.get(ACCESS_COOKIE) != old_access
    assert client.get('/api/auth/me').json()['home'] == '/student'
    assert client.get('/student').status_code == 200
    assert client.get('/change-password').headers['location'] == '/student'

    client.post('/api/auth/logout')
    assert login(client, 'new@example.test', TEMP).status_code == 401
    assert login(client, 'new@example.test', 'a-new-password').json()['home'] == '/student'


def test_supabase_password_rules_and_a_failed_flag_update_are_reported(world):
    client, users, state = world
    login(client, 'new@example.test', TEMP)
    weak = change(client, TEMP, 'password1234')
    assert weak.status_code == 422 and weak.json()['detail']['code'] == 'WEAK_PASSWORD'
    assert 'breach' in weak.json()['detail']['message']
    assert users['new@example.test']['password'] == TEMP

    state['fail_flag'] = True
    failed = change(client, TEMP, 'a-new-password')
    assert failed.status_code == 502 and failed.json()['detail']['code'] == 'PASSWORD_FLAG_NOT_CLEARED'
    assert client.get('/api/auth/me').json()['must_change_password'] is True  # still asked to change
    state['fail_flag'] = False
    assert change(client, 'a-new-password', 'another-password').json()['must_change_password'] is False


def test_accounts_without_the_flag_are_not_affected(world):
    client, _, state = world
    response = login(client, 'old@example.test', 'long-standing-pass')
    assert response.json()['must_change_password'] is False and response.json()['home'] == '/lecturer'
    assert client.get('/change-password').headers['location'] == '/lecturer'
    assert client.get('/lecturer').status_code == 200
    assert change(client, 'long-standing-pass', 'a-new-password').status_code == 200
    assert not any(c[1].startswith('/auth/v1/admin/') for c in state['calls'])
    client.post('/api/auth/logout')
    assert change(client, 'a-new-password', 'third-password').status_code == 401  # needs a login
