"""Login, sessions, page redirects and role-based API access, against a local
stand-in for Supabase Auth and the role tables. No hosted project is contacted."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import count
from threading import Thread
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from backend.app.auth import ACCESS_COOKIE, REFRESH_COOKIE, SessionUser, get_session
from backend.app.config import load_settings
from backend.app.main import create_app
from backend.app.scheduling.preview import PAGE_PATH

BASE = "http://127.0.0.1:8000"
PASSWORD = "correct-horse-test-only"


def uid(number):
    return str(UUID(int=number))


ACCOUNTS = {  # email -> auth user id
    "admin@example.test": uid(1), "lecturer@example.test": uid(2), "student@example.test": uid(3),
    "both@example.test": uid(4), "nobody@example.test": uid(5), "unconfirmed@example.test": uid(6),
}
TABLES = {
    "admins": [{"id": uid(101), "full_name": "Ada Admin", "auth_user_id": uid(1)},
               {"id": uid(104), "full_name": "Bo Both", "auth_user_id": uid(4)}],
    "lecturers": [{"id": uid(201), "full_name": "Lee Lecturer", "lecturer_code": "LEC001", "auth_user_id": uid(2)},
                  {"id": uid(202), "full_name": "Other Lecturer", "lecturer_code": "LEC002", "auth_user_id": None},
                  {"id": uid(204), "full_name": "Bo Both", "lecturer_code": "LEC004", "auth_user_id": uid(4)}],
    "students": [{"id": uid(301), "full_name": "Sam Student", "student_code": "TP000001", "auth_user_id": uid(3),
                  "student_intakes": []}],
    "class_session_details": [{"id": uid(401), "lecturer_id": uid(202), "status": "scheduled"},
                              {"id": uid(402), "lecturer_id": uid(202), "status": "cancelled"}],
    "class_sessions": [],
}


@pytest.fixture
def supabase(monkeypatch):
    state = {"access": {}, "refresh": {}, "calls": [], "counter": count(1)}

    def issue(user_id):
        n = next(state["counter"])
        access, refresh = f"access-{n}", f"refresh-{n}"
        state["access"][access] = user_id
        state["refresh"][refresh] = user_id
        email = next(e for e, u in ACCOUNTS.items() if u == user_id)
        return {"access_token": access, "refresh_token": refresh, "expires_in": 3600, "token_type": "bearer",
                "user": {"id": user_id, "email": email}}

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            parsed = urlsplit(self.path)
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            state["calls"].append({"method": "POST", "path": parsed.path, "body": body})
            grant = parse_qs(parsed.query).get("grant_type", [None])[0]
            if parsed.path == "/auth/v1/token" and grant == "password":
                user_id = ACCOUNTS.get(body.get("email"))
                if user_id is None or body.get("password") != PASSWORD:
                    return self.reply(400, {"code": 400, "error_code": "invalid_credentials", "msg": "Invalid login credentials"})
                if body["email"].startswith("unconfirmed"):
                    return self.reply(400, {"code": 400, "error_code": "email_not_confirmed", "msg": "Email not confirmed"})
                return self.reply(200, issue(user_id))
            if parsed.path == "/auth/v1/token" and grant == "refresh_token":
                user_id = state["refresh"].pop(body.get("refresh_token"), None)
                return self.reply(200, issue(user_id)) if user_id else self.reply(400, {"error_code": "refresh_token_not_found"})
            if parsed.path == "/auth/v1/logout":
                token = self.headers.get("Authorization", "").removeprefix("Bearer ")
                state["access"].pop(token, None)
                return self.reply(204, {})
            self.reply(404, {})

        def do_PATCH(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            state["calls"].append({"method": "PATCH", "path": urlsplit(self.path).path, "body": body})
            self.send_response(204)
            self.end_headers()

        def do_GET(self):
            parsed = urlsplit(self.path)
            params = parse_qs(parsed.query)
            state["calls"].append({"method": "GET", "path": parsed.path, "params": params})
            if parsed.path == "/auth/v1/user":
                token = self.headers.get("Authorization", "").removeprefix("Bearer ")
                user_id = state["access"].get(token)
                if user_id is None:
                    return self.reply(401, {"msg": "invalid JWT"})
                return self.reply(200, {"id": user_id, "email": next(e for e, u in ACCOUNTS.items() if u == user_id)})
            rows = list(TABLES.get(parsed.path.removeprefix("/rest/v1/"), []))
            for key, values in params.items():
                if key in ("select", "limit", "order", "offset"):
                    continue
                expected = values[0].removeprefix("eq.")
                if not values[0].startswith(("gte.", "lt.", "in.")):
                    rows = [row for row in rows if str(row.get(key)) == expected]
            self.reply(200, rows)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    settings = load_settings()
    settings.supabase.url_env, settings.supabase.key_env = "AUTH_TEST_URL", "AUTH_TEST_KEY"
    monkeypatch.setenv("AUTH_TEST_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("AUTH_TEST_KEY", "sb_secret_auth_test")
    yield settings, state
    server.shutdown()
    server.server_close()


@pytest.fixture
def frontend(tmp_path):
    (tmp_path / "index.html").write_text('<div id="app">SClass</div>')
    return tmp_path


def client(settings, frontend):
    return TestClient(create_app(settings, frontend), base_url=BASE, client=("127.0.0.1", 51000), follow_redirects=False)


def login(c, email, password=PASSWORD):
    return c.post("/api/auth/login", json={"email": email, "password": password})


def cookie_header(response, name):
    return next((value for value in response.headers.get_list("set-cookie") if value.startswith(f"{name}=")), "")


@pytest.mark.parametrize("email,role,home,code", [
    ("admin@example.test", "admin", "/admin", None),
    ("lecturer@example.test", "lecturer", "/lecturer", "LEC001"),
    ("student@example.test", "student", "/student", "TP000001"),
    ("both@example.test", "admin", "/admin", None),  # admin > lecturer > student
])
def test_login_sets_httponly_session_and_resolves_one_role(supabase, frontend, email, role, home, code):
    settings, _ = supabase
    with client(settings, frontend) as c:
        response = login(c, f"  {email} ")
        assert response.status_code == 200, response.text
        data = response.json()
        assert (data["role"], data["home"], data["code"]) == (role, home, code)
        assert response.headers["cache-control"] == "no-store"
        for name in (ACCESS_COOKIE, REFRESH_COOKIE):
            header = cookie_header(response, name).lower()
            assert "httponly" in header and "samesite=lax" in header and "path=/" in header
            assert "secure" not in header  # plain http on localhost
        assert "access_token" not in response.text and "refresh" not in response.text
        me = c.get("/api/auth/me")
        assert me.status_code == 200 and me.json()["role"] == role


@pytest.mark.parametrize("email,password,status,code", [
    ("student@example.test", "wrong", 401, "INVALID_CREDENTIALS"),
    ("unknown@example.test", PASSWORD, 401, "INVALID_CREDENTIALS"),
    ("nobody@example.test", PASSWORD, 403, "ACCOUNT_NOT_LINKED"),
    ("unconfirmed@example.test", PASSWORD, 403, "EMAIL_NOT_CONFIRMED"),
])
def test_failed_login_sets_no_session(supabase, frontend, email, password, status, code):
    settings, state = supabase
    with client(settings, frontend) as c:
        response = login(c, email, password)
        assert response.status_code == status and response.json()["detail"]["code"] == code
        assert not response.headers.get_list("set-cookie")
        assert password not in response.text
        assert c.get("/api/auth/me").status_code == 401
    if code == "ACCOUNT_NOT_LINKED":  # the Supabase session is revoked again
        assert any(call["path"] == "/auth/v1/logout" for call in state["calls"])


@pytest.mark.parametrize("body", [{}, {"email": "student@example.test"}, {"email": "no-at-sign", "password": "x"},
                                  {"email": "a@b.c", "password": ""}, {"email": "a@b.c", "password": "x", "role": "admin"}])
def test_malformed_login_is_rejected_before_supabase(supabase, frontend, body):
    settings, state = supabase
    with client(settings, frontend) as c:
        assert c.post("/api/auth/login", json=body).status_code == 422
    assert not state["calls"]


def test_expired_access_token_is_refreshed_and_invalid_session_is_cleared(supabase, frontend):
    settings, state = supabase
    with client(settings, frontend) as c:
        c.app.state.auth_sessions.ttl = 0  # no caching: every request asks Supabase
        assert login(c, "student@example.test").status_code == 200
        state["access"].clear()  # access token expired
        refreshed = c.get("/api/auth/me")
        assert refreshed.status_code == 200 and refreshed.json()["role"] == "student"
        assert cookie_header(refreshed, ACCESS_COOKIE) and cookie_header(refreshed, REFRESH_COOKIE)
        assert c.get("/api/auth/me").status_code == 200  # the new cookies work
        state["access"].clear()
        state["refresh"].clear()  # refresh token revoked too
        gone = c.get("/api/auth/me")
        assert gone.status_code == 401
        assert "max-age=0" in cookie_header(gone, ACCESS_COOKIE).lower()


def test_logout_revokes_and_clears_the_session(supabase, frontend):
    settings, state = supabase
    with client(settings, frontend) as c:
        assert login(c, "lecturer@example.test").status_code == 200
        response = c.post("/api/auth/logout")
        assert response.status_code == 200
        assert "max-age=0" in cookie_header(response, ACCESS_COOKIE).lower()
        assert any(call["path"] == "/auth/v1/logout" for call in state["calls"])
        assert c.get("/api/auth/me").status_code == 401
        assert c.post("/api/auth/logout").status_code == 200  # logging out twice is harmless


def test_pages_redirect_to_login_and_to_the_users_own_area(supabase, frontend):
    settings, _ = supabase
    with client(settings, frontend) as c:
        for path in ("/student", "/lecturer", "/admin"):
            response = c.get(path)
            assert response.status_code == 303 and response.headers["location"] == f"/login?next={path}"
        assert c.get("/").headers["location"] == "/login"
        assert c.get("/login").status_code == 200
        assert login(c, "student@example.test").status_code == 200
        assert c.get("/").headers["location"] == "/student"
        assert c.get("/student").status_code == 200
        assert c.get("/lecturer").headers["location"] == "/student"
        assert c.get("/admin").headers["location"] == "/student"
        assert c.get("/login").headers["location"] == "/student"
        for unsafe in ("//evil.example", "https://evil.example", "/admin", "/api/auth/me", "/\\evil"):
            assert c.get("/login", params={"next": unsafe}).headers["location"] == "/student"


def test_student_can_only_read_their_own_timetable(supabase, frontend):
    settings, _ = supabase
    week = {"start": "2026-11-09T00:00:00+08:00", "end": "2026-11-16T00:00:00+08:00"}
    with client(settings, frontend) as c:
        assert c.get("/api/student/TP000001/timetable", params=week).status_code == 401
        login(c, "student@example.test")
        assert c.get("/api/student/TP000001/timetable", params=week).status_code == 200
        other = c.get("/api/student/TP000002/timetable", params=week)
        assert other.status_code == 403 and other.json()["detail"] == "You can only view your own timetable."
        assert c.get("/api/student/TP000002").status_code == 403
        assert c.get("/api/lecturers").status_code == 403
        assert c.get("/api/rooms").status_code == 200


def test_lecturer_sees_and_changes_only_their_own_classes(supabase, frontend):
    settings, state = supabase
    own, other = uid(201), uid(202)
    move = {"session_date": "2026-11-20", "start_time": "10:00", "room_id": uid(9)}
    with client(settings, frontend) as c:
        login(c, "lecturer@example.test")
        assert c.get("/api/lecturers").json() == [{"id": own, "name": "Lee Lecturer"}]
        assert c.get(f"/api/lecturers/{other}/timetable", params={"start": "2026-11-09"}).status_code == 403
        assert c.get(f"/api/lecturers/{own}/timetable", params={"start": "2026-11-09"}).status_code == 200
        # The class belongs to another lecturer: rejected whichever id is in the URL.
        assert c.patch(f"/api/lecturers/{own}/sessions/{uid(401)}", json=move).status_code == 403
        assert c.patch(f"/api/lecturers/{other}/sessions/{uid(401)}", json=move).status_code == 403
        assert c.get("/api/student/TP000001/timetable", params={"start": "2026-11-09T00:00:00Z", "end": "2026-11-10T00:00:00Z"}).status_code == 403
    assert not any(call["method"] == "PATCH" for call in state["calls"])


def test_admin_can_read_any_record_and_reschedule_on_behalf(supabase, frontend):
    settings, state = supabase
    with client(settings, frontend) as c:
        login(c, "admin@example.test")
        assert len(c.get("/api/lecturers").json()) == 3
        assert c.get("/api/student/TP000001").status_code == 200
        move = {"session_date": "2026-11-20", "start_time": "10:00", "room_id": uid(9)}
        assert c.patch(f"/api/lecturers/{uid(202)}/sessions/{uid(401)}", json=move).status_code == 200
        # A cancelled class cannot be moved (that would silently reactivate it).
        assert c.patch(f"/api/lecturers/{uid(202)}/sessions/{uid(402)}", json=move).status_code == 409
    patches = [call for call in state["calls"] if call["method"] == "PATCH"]
    assert len(patches) == 1 and patches[0]["body"]["status"] == "rescheduled"


def test_scheduling_page_and_apis_require_an_admin(supabase, frontend):
    settings, _ = supabase
    body = {"week_start": "2026-11-09", "intake_id": uid(1)}
    with client(settings, frontend) as c:
        page = c.get(PAGE_PATH)
        assert page.status_code == 303 and page.headers["location"] == f"/login?next={PAGE_PATH}"
        assert c.get(PAGE_PATH + "/app.js").status_code == 401
        unauthenticated = c.post("/api/schedules/generate", json=body)
        assert unauthenticated.status_code == 401 and unauthenticated.json()["detail"]["code"] == "AUTH_REQUIRED"
        login(c, "lecturer@example.test")
        assert c.get(PAGE_PATH).headers["location"] == "/lecturer"
        forbidden = c.post("/api/schedules/save", json=body)
        assert forbidden.status_code == 403 and forbidden.json()["detail"]["code"] == "ADMIN_REQUIRED"
        c.post("/api/auth/logout")
        login(c, "admin@example.test")
        assert c.get(PAGE_PATH).status_code == 200
        assert c.get(PAGE_PATH + "/app.js").status_code == 200
        assert c.get(f"/login?next={PAGE_PATH}").headers["location"] == PAGE_PATH
    settings.app.environment = "production"
    with client(settings, frontend) as c:
        login(c, "admin@example.test")
        assert c.get(PAGE_PATH).status_code == 404  # development-only, even for admins


def test_session_is_cached_briefly_instead_of_checked_on_every_request(supabase, frontend):
    settings, state = supabase
    with client(settings, frontend) as c:
        login(c, "student@example.test")
        before = sum(call["path"] == "/auth/v1/user" for call in state["calls"])
        for _ in range(3):
            assert c.get("/api/auth/me").status_code == 200
        assert sum(call["path"] == "/auth/v1/user" for call in state["calls"]) == before


def test_missing_supabase_configuration_is_reported(frontend, monkeypatch):
    settings = load_settings()
    settings.supabase.url_env, settings.supabase.key_env = "AUTH_MISSING_URL", "AUTH_MISSING_KEY"
    monkeypatch.delenv("AUTH_MISSING_URL", raising=False)
    with client(settings, frontend) as c:
        response = login(c, "student@example.test")
        assert response.status_code == 503 and response.json()["detail"]["code"] == "AUTH_NOT_CONFIGURED"


def test_dependency_override_is_available_for_other_tests(frontend):
    """Other suites act as a user by overriding get_session."""
    app = create_app(load_settings(), frontend)
    app.dependency_overrides[get_session] = lambda: SessionUser(role="admin", name="T", profile_id=uid(1), home="/admin")
    with TestClient(app, base_url=BASE, follow_redirects=False) as c:
        assert c.get("/api/auth/me").json()["role"] == "admin"
        assert c.get("/").headers["location"] == "/admin"
