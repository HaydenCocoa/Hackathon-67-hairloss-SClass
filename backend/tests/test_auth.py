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
    "class_session_details": [
        {"id": uid(401), "lecturer_id": uid(202), "status": "scheduled", "starts_at": "2026-11-25T02:00:00+00:00",
         "room_id": uid(9), "section_id": uid(501), "intake_id": uid(601), "group_number": 1, "duration_minutes": 90},
        {"id": uid(402), "lecturer_id": uid(202), "status": "cancelled", "starts_at": "2026-11-25T05:00:00+00:00",
         "room_id": uid(9), "section_id": uid(501), "intake_id": uid(601), "group_number": 1, "duration_minutes": 90}],
    "rooms": [{"id": uid(9), "name": "R9", "building": "B", "capacity": 40, "room_type": "classroom", "is_active": True}],
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
            state["calls"].append({"method": "POST", "path": parsed.path, "body": body,
                                   "authorization": self.headers.get("Authorization")})
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
            if parsed.path == "/rest/v1/schedule_changes":
                return self.reply(201, [body])
            if parsed.path.startswith("/rest/v1/rpc/"):
                return self.reply(200, None)
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
                if key == "action" and values[0].startswith("in.("):
                    rows = [row for row in rows if row.get("action") in values[0][4:-1].split(",")]
                elif not values[0].startswith(("gte.", "lt.", "in.", "not.")):
                    # JSON-style comparison, so is_active=eq.true matches a Python True.
                    rows = [row for row in rows if json.dumps(row.get(key)).strip('"') == expected]
            offset = int(params.get("offset", ["0"])[0])
            limit = int(params.get("limit", [str(len(rows))])[0])
            self.reply(200, rows[offset:offset + limit])

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
        # The Supabase user id is kept server-side for the save audit only.
        assert "auth_user_id" not in data and "auth_user_id" not in me.json()
        assert ACCOUNTS[email] not in response.text + me.text


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
        for path in ("/student", "/lecturer", "/admin", "/admin/schedule"):
            response = c.get(path)
            assert response.status_code == 303 and response.headers["location"] == f"/login?next={path}"
        assert c.get("/").headers["location"] == "/login"
        assert c.get("/login").status_code == 200
        assert login(c, "student@example.test").status_code == 200
        assert c.get("/").headers["location"] == "/student"
        assert c.get("/student").status_code == 200
        assert c.get("/lecturer").headers["location"] == "/student"
        assert c.get("/admin").headers["location"] == "/student"
        assert c.get("/admin/schedule").headers["location"] == "/student"
        assert c.get("/login").headers["location"] == "/student"
        for unsafe in ("//evil.example", "https://evil.example", "/admin", "/api/auth/me", "/\\evil"):
            assert c.get("/login", params={"next": unsafe}).headers["location"] == "/student"


def test_student_changes_hide_save_audit_rows(supabase, frontend, monkeypatch):
    """A 'create' audit row (written when an admin saves a timetable) is not a change to show students."""
    settings, state = supabase
    section, intake, session_id = uid(501), uid(601), uid(411)
    starts = "2026-11-10T02:00:00+00:00"
    booking = {"id": session_id, "section_id": section, "starts_at": starts, "status": "scheduled"}
    monkeypatch.setitem(TABLES, "students", [{**TABLES["students"][0], "student_intakes": [
        {"group_number": 1, "intakes": {"id": intake, "intake_code": "I1"}}]}])
    monkeypatch.setitem(TABLES, "course_offerings", [{"id": uid(701), "intake_id": intake,
                                                      "class_sections": [{"id": section, "group_number": 1}]}])
    monkeypatch.setitem(TABLES, "class_session_details", [{
        **booking, "room_id": None, "lecturer_id": None, "ends_at": "2026-11-10T03:30:00+00:00",
        "course_code": "C1", "course_name": "Subject", "course_type": "lecture"}])
    monkeypatch.setitem(TABLES, "schedule_changes", [
        {"action": action, "reason": None, "old_values": old, "new_values": {"starts_at": starts},
         "created_at": "2026-11-09T01:00:00+00:00", "class_session_id": session_id, "class_sessions": booking}
        for action, old in (("create", {}), ("reschedule", {"starts_at": "2026-11-09T02:00:00+00:00"}))])
    week = {"start": "2026-11-09T00:00:00+08:00", "end": "2026-11-16T00:00:00+08:00"}
    with client(settings, frontend) as c:
        login(c, "student@example.test")
        response = c.get("/api/student/TP000001/timetable", params=week)
        assert response.status_code == 200, response.text
        data = response.json()
    assert [change["action"] for change in data["recent_changes"]] == ["reschedule"]
    assert data["classes"][0]["latest_change"]["action"] == "reschedule"
    query = next(call for call in state["calls"] if call["path"] == "/rest/v1/schedule_changes")
    assert query["params"]["action"] == ["in.(cancel,reschedule)"]


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
        # A cancelled class cannot be moved (that would silently reactivate it).
        assert c.patch(f"/api/lecturers/{uid(202)}/sessions/{uid(402)}", json=move).status_code == 409
    # Since 12 November 2026 a move is one database function call (admin_reschedule_class for an admin,
    # recording the admin as changed_by); the successful on-behalf move is tested in
    # test_lecturer_reschedule.py with data the scheduling engine can check. Never direct writes:
    assert not any(call["method"] == "PATCH" for call in state["calls"])
    assert not any(call["path"] in ("/rest/v1/schedule_changes", "/rest/v1/class_sessions")
                   for call in state["calls"] if call["method"] == "POST")


def test_lecturer_timetable_shows_the_real_intake_code_and_group_size(supabase, frontend, monkeypatch):
    settings, _ = supabase
    row = {**TABLES["class_session_details"][0], "lecturer_id": uid(201), "ends_at": "2026-11-25T03:30:00+00:00",
           "course_code": "C1", "course_type": "lecture", "course_name": "Subject"}
    monkeypatch.setitem(TABLES, "class_session_details", [row])
    monkeypatch.setitem(TABLES, "intakes", [{"id": uid(601), "intake_code": "APU1F2611CS"}])
    monkeypatch.setitem(TABLES, "student_intakes", [
        {"student_id": uid(301 + n), "intake_id": uid(601), "group_number": 1} for n in range(3)
    ] + [{"student_id": uid(399), "intake_id": uid(601), "group_number": 2}])
    with client(settings, frontend) as c:
        login(c, "lecturer@example.test")
        response = c.get(f"/api/lecturers/{uid(201)}/timetable", params={"start": "2026-11-23", "end": "2026-11-29"})
    assert response.status_code == 200, response.text
    [session] = response.json()
    assert (session["intake_code"], session["student_count"]) == ("APU1F2611CS", 3)


def test_admin_api_accepts_the_login_session(supabase, frontend):
    """The admin page works for a logged-in admin without pasting a Supabase token."""
    settings, state = supabase
    with client(settings, frontend) as c:
        assert c.get("/api/admin/timetable/rooms").status_code == 401
        login(c, "student@example.test")
        assert c.get("/api/admin/timetable/rooms").status_code == 403
        c.post("/api/auth/logout")
        login(c, "admin@example.test")
        rooms = c.get("/api/admin/timetable/rooms")
        assert rooms.status_code == 200 and rooms.json()[0]["id"] == uid(9)
        # An empty "Bearer " (blank token box on the page) falls back to the session too.
        assert c.get("/api/admin/courses", headers={"Authorization": "Bearer "}).status_code == 200
        access = c.cookies.get(ACCESS_COOKIE)
        move = {"expected_start": "2026-11-25T02:00:00Z", "expected_room": uid(9), "new_start": "2026-11-25T04:00:00Z",
                "new_room": uid(9), "reason": "Clash"}
        assert c.put(f"/api/admin/timetable/{uid(401)}", json=move).status_code == 200
    rpc = [call for call in state["calls"] if call["path"] == "/rest/v1/rpc/admin_reschedule_class"]
    # The database function runs as the logged-in admin (auth.uid()), not with the server key.
    assert len(rpc) == 1 and rpc[0]["authorization"] == f"Bearer {access}"


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
    app.dependency_overrides[get_session] = lambda: SessionUser(role="admin", name="T", profile_id=uid(1), home="/admin", auth_user_id=uid(2))
    with TestClient(app, base_url=BASE, follow_redirects=False) as c:
        assert c.get("/api/auth/me").json()["role"] == "admin"
        assert c.get("/").headers["location"] == "/admin"
        # The scheduling workspace opened from Admin > Timetable > Schedule Class.
        assert c.get("/admin/schedule").status_code == 200
        assert c.get("/login", params={"next": "/admin/schedule"}).headers["location"] == "/admin/schedule"
