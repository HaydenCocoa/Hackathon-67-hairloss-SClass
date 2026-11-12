import httpx
from fastapi.testclient import TestClient

from backend.app.config import load_settings
from backend.app.main import create_app

ADMIN_ID = '00000000-0000-4000-8000-000000000001'
SESSION_ID = '00000000-0000-4000-8000-000000000002'
ROOM_ID = '00000000-0000-4000-8000-000000000003'


def test_timetable_requires_admin_and_passes_user_token_to_rpc(monkeypatch):
    settings = load_settings()
    settings.supabase.url_env = 'TEST_ADMIN_URL'
    settings.supabase.key_env = 'TEST_ADMIN_KEY'
    monkeypatch.setenv('TEST_ADMIN_URL', 'http://test-supabase')
    monkeypatch.setenv('TEST_ADMIN_KEY', 'test-key')
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path == '/auth/v1/user':
            if request.headers.get('authorization') != 'Bearer admin-token':
                return httpx.Response(401)
            return httpx.Response(200, json={'id': ADMIN_ID})
        if request.url.path == '/rest/v1/admins':
            return httpx.Response(200, json=[{'id': ADMIN_ID}])
        if request.url.path == '/rest/v1/rpc/admin_reschedule_class':
            assert request.headers['authorization'] == 'Bearer admin-token'
            return httpx.Response(200, json=None)
        if request.url.path == '/rest/v1/rpc/admin_remove_cancelled_class':
            return httpx.Response(400, json={'code': 'P0002'})
        if request.url.path == '/rest/v1/class_session_details':
            offset = int(request.url.params['offset'])
            return httpx.Response(200, json=[{'id': SESSION_ID}] if offset == 0 else [])
        raise AssertionError(request.url)

    app = create_app(settings)
    with TestClient(app) as client:
        app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        assert client.get('/api/admin/timetable', params={'start': '2026-11-10T00:00:00Z', 'end': '2026-11-11T00:00:00Z'}).status_code == 401
        headers = {'Authorization': 'Bearer admin-token'}
        response = client.get('/api/admin/timetable', headers=headers, params={'start': '2026-11-10T00:00:00Z', 'end': '2026-11-11T00:00:00Z'})
        assert response.status_code == 200
        assert response.json()[0]['id'] == SESSION_ID
        assert [str(call.url.params.get('offset')) for call in calls if call.url.path == '/rest/v1/class_session_details'] == ['0', '1']
        payload = {'expected_start': '2026-11-10T09:00:00Z', 'expected_room': ROOM_ID,
                   'new_start': '2026-11-10T10:00:00Z', 'new_room': ROOM_ID, 'reason': 'Change'}
        assert client.put(f'/api/admin/timetable/{SESSION_ID}', headers=headers, json=payload).status_code == 200
        assert client.put(f'/api/admin/timetable/{SESSION_ID}', headers=headers, json={**payload, 'reason': ' '}).status_code == 422
        assert client.delete(f'/api/admin/timetable/{SESSION_ID}', headers=headers).status_code == 404
