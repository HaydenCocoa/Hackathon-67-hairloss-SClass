import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from time import sleep

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.auth import SessionUser, get_session
from backend.app import config as config_module
from backend.app.config import load_settings
from backend.app.main import create_app


def logged_in(app):
    """Database health needs a login; act as a logged-in student."""
    app.dependency_overrides[get_session] = lambda: SessionUser(role="student", name="T", profile_id="s", code="S1", home="/student",
                                                                auth_user_id="00000000-0000-0000-0000-0000000000a1")
    return app


@pytest.fixture
def settings(monkeypatch):
    settings = load_settings()
    # Dedicated names ensure tests never use a developer's real credentials.
    settings.supabase.url_env = "TEST_SUPABASE_URL"
    settings.supabase.key_env = "TEST_SUPABASE_KEY"
    monkeypatch.delenv("TEST_SUPABASE_URL", raising=False)
    monkeypatch.delenv("TEST_SUPABASE_KEY", raising=False)
    return settings


@pytest.fixture
def upstream():
    state = {"status": 200, "body": b'[]', "delay": 0, "calls": []}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state["calls"].append({"path": self.path, "headers": dict(self.headers)})
            sleep(state["delay"])
            self.send_response(state["status"])
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            try:
                self.wfile.write(state["body"])
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", state
    server.shutdown()
    server.server_close()
    thread.join()


def test_boot_config_and_health(settings, tmp_path):
    with TestClient(create_app(settings, tmp_path)) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        assert client.get("/api/config").json() == settings.app.model_dump()
        assert client.get("/Config/config.json").status_code == 404
        assert client.get("/Config/preference.json").status_code == 404
        assert client.get("/.env").status_code == 404
        assert client.get("/api/missing").status_code == 404
        assert client.get("/", follow_redirects=False).headers["location"] == "/login"
        assert client.get("/login").status_code == 503  # no frontend build in tmp_path
        assert client.get("/api/health/database").status_code == 401  # login required
        assert "/api/health/database" in client.get("/openapi.json").json()["paths"]


def test_missing_credentials_does_not_block_boot(settings):
    with TestClient(logged_in(create_app(settings))) as client:
        response = client.get("/api/health/database")
        assert response.status_code == 503
        assert response.json()["status"] == "not_configured"


def test_startup_uses_configured_teaching_calendar(settings):
    from datetime import date

    settings.scheduling.opening_hours["monday"].opens_at = "09:17"
    app = create_app(settings)
    opens_at, closes_at = app.state.teaching_calendar.opening_window(date(2026, 11, 9))
    assert opens_at.isoformat() == "2026-11-09T09:17:00+08:00"
    assert closes_at.isoformat() == "2026-11-09T18:00:00+08:00"


@pytest.mark.parametrize("key", ["sb_secret_test-only", "eyJtest-legacy-key"])
def test_query_uses_real_http_and_keeps_rows_private(settings, upstream, monkeypatch, key):
    url, state = upstream
    state["body"] = b'[{"id":"private-room-id"}]'
    monkeypatch.setenv("TEST_SUPABASE_URL", url)
    monkeypatch.setenv("TEST_SUPABASE_KEY", key)
    with TestClient(logged_in(create_app(settings))) as client:
        response = client.get("/api/health/database")
        assert response.status_code == 200
        assert response.json()["status"] == "connected"
        assert response.json()["latency_ms"] >= 0
        assert key not in response.text
        assert "private-room-id" not in response.text
        assert key not in client.get("/api/config").text
    call = state["calls"][0]
    assert call["path"] == "/rest/v1/rooms?select=id&limit=1"
    assert call["headers"]["apikey"] == key
    assert call["headers"].get("Authorization") == (f"Bearer {key}" if key.startswith("eyJ") else None)


@pytest.mark.parametrize("status,body", [
    (401, b'{"message":"secret upstream error"}'),
    (403, b'{}'), (404, b'{}'), (500, b'<html>error</html>'),
    (200, b'not json'), (200, b'{"unexpected":true}'),
])
def test_failed_queries_do_not_report_success(settings, upstream, monkeypatch, status, body):
    url, state = upstream
    state.update(status=status, body=body)
    monkeypatch.setenv("TEST_SUPABASE_URL", url)
    monkeypatch.setenv("TEST_SUPABASE_KEY", "sb_secret_test-only")
    with TestClient(logged_in(create_app(settings))) as client:
        response = client.get("/api/health/database")
        assert response.status_code == 503
        assert response.json()["status"] == "error"
        assert "secret upstream error" not in response.text
        assert "sb_secret_test-only" not in response.text


def test_timeout(settings, upstream, monkeypatch):
    url, state = upstream
    state["delay"] = 0.3
    settings.supabase.timeout_seconds = 0.05
    monkeypatch.setenv("TEST_SUPABASE_URL", url)
    monkeypatch.setenv("TEST_SUPABASE_KEY", "test-key")
    with TestClient(logged_in(create_app(settings))) as client:
        response = client.get("/api/health/database")
        assert response.status_code == 503
        assert response.json()["status"] == "timeout"


def test_disallowed_http_url(settings, monkeypatch):
    monkeypatch.setenv("TEST_SUPABASE_URL", "http://example.com")
    monkeypatch.setenv("TEST_SUPABASE_KEY", "test-key")
    with TestClient(logged_in(create_app(settings))) as client:
        assert client.get("/api/health/database").json()["status"] == "error"


def test_invalid_boot_config_fails_early(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"app": {"name": "SClass"}}))
    with pytest.raises(ValidationError):
        load_settings(path)


def test_config_path_prefers_repository_copy_and_falls_back_to_bundled_copy(tmp_path, monkeypatch):
    # Vercel bundles only backend/; its build step copies Config/ into backend/Config/.
    project, backend = tmp_path / "project", tmp_path / "project" / "backend"
    primary, bundled = project / "Config" / "config.json", backend / "Config" / "config.json"
    monkeypatch.setattr(config_module, "PROJECT_ROOT", project)
    monkeypatch.setattr(config_module, "BACKEND_ROOT", backend)
    bundled.parent.mkdir(parents=True)
    bundled.write_text("{}")
    assert config_module.default_config_path() == bundled
    primary.parent.mkdir(parents=True)
    primary.write_text("{}")
    assert config_module.default_config_path() == primary
    bundled.unlink()
    primary.unlink()
    assert config_module.default_config_path() == primary  # missing file still reports the real location


def test_built_frontend_is_served_without_exposing_other_files(settings, tmp_path):
    (tmp_path / "index.html").write_text('<div id="app">SClass</div>')
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "app.js").write_text('console.log("SClass")')
    with TestClient(create_app(settings, tmp_path)) as client:
        assert client.get("/login").status_code == 200
        assert client.get("/student", follow_redirects=False).headers["location"] == "/login?next=/student"
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/api/health").json()["status"] == "ok"
        assert client.get("/Config/config.json").status_code == 404


@pytest.mark.skipif(not os.getenv("SUPABASE_SIMULATION_URL"), reason="Optional Postman simulation is not running")
def test_postman_simulation(settings, monkeypatch):
    monkeypatch.setenv("TEST_SUPABASE_URL", os.environ["SUPABASE_SIMULATION_URL"])
    with TestClient(logged_in(create_app(settings))) as client:
        for key, expected in [("sb_secret_simulation", "connected"), ("invalid-key", "error")]:
            monkeypatch.setenv("TEST_SUPABASE_KEY", key)
            response = client.get("/api/health/database")
            assert response.status_code == (200 if expected == "connected" else 503)
            assert response.json()["status"] == expected
