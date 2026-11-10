"""Local UI QA service with synthetic PostgreSQL data, never hosted credentials.

Run: python -m backend.tests.serve_schedule_preview
Requires the same Node/PGlite tooling as the snapshot integration tests.
"""
import copy
import json
import os
import subprocess
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from zoneinfo import ZoneInfo

import uvicorn

from backend.app.config import PROJECT_ROOT, load_settings
from backend.app.main import create_app


def main():
    exported = subprocess.run(
        ["node", str(PROJECT_ROOT / "supabase/tests/scheduling-snapshot.fixture.cjs")],
        cwd=PROJECT_ROOT, env={**os.environ, "NODE_PATH": str(PROJECT_ROOT / ".sql-tools/node_modules")},
        capture_output=True, text=True, check=True, timeout=30,
    )
    payload = json.loads(exported.stdout)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            parameters = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            week = parameters.get("p_week_start")
            data = copy.deepcopy(payload)
            if week != "2026-11-09":
                start = datetime.combine(date.fromisoformat(week), datetime.min.time(), ZoneInfo("Asia/Kuala_Lumpur"))
                data.update(week_start=week, horizon_starts_at=start.isoformat(), horizon_ends_at=(start + timedelta(days=7)).isoformat(),
                            requirements=[], rosters=[], class_bookings=[], meeting_bookings=[])
            self.send_response(200 if self.path == "/rest/v1/rpc/load_scheduling_data" else 501)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())

        def log_message(self, *_):
            pass

    provider = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=provider.serve_forever, daemon=True)
    thread.start()
    settings = load_settings()
    settings.app.environment = "development"
    settings.supabase.url_env, settings.supabase.key_env = "SCHEDULING_UI_QA_URL", "SCHEDULING_UI_QA_KEY"
    os.environ[settings.supabase.url_env] = f"http://127.0.0.1:{provider.server_port}"
    os.environ[settings.supabase.key_env] = "sb_secret_synthetic_ui_qa"
    try:
        uvicorn.run(create_app(settings), host="127.0.0.1", port=8001, proxy_headers=False)
    finally:
        provider.shutdown()
        provider.server_close()
        thread.join()


if __name__ == "__main__":
    main()
