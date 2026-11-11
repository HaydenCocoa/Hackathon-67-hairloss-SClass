"""Local UI QA service with synthetic PostgreSQL data, never hosted credentials.

Run: python -m backend.tests.serve_schedule_preview
Requires the same Node/PGlite tooling as the snapshot integration tests.
"""
import copy
import json
import os
import subprocess
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlsplit

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
        def do_GET(self):
            parsed = urlsplit(self.path)
            params = {key: value[0] for key, value in parse_qs(parsed.query).items()}
            data = copy.deepcopy(payload)
            requirements = data["requirements"] if params.get("target_week_start") == "eq.2026-11-09" else []
            bookings = data["class_bookings"]
            table = parsed.path.removeprefix("/rest/v1/")
            source = {
                "teaching_occurrence_details": requirements,
                "class_session_details": [{key: row[key] for key in
                                           ("id", "section_id", "room_id", "starts_at", "ends_at", "status",
                                            "group_number", "intake_id", "lecturer_id", "duration_minutes")}
                                          for row in bookings],
                "class_sessions": [{"id": row["id"], "occurrence_id": row["occurrence_id"]} for row in bookings],
                "meeting_sessions": [{key: row[key] for key in
                                      ("id", "lecturer_id", "room_id", "starts_at", "ends_at", "status")}
                                     for row in data["meeting_bookings"]],
                "meeting_students": [{"meeting_id": row["id"], "student_id": student_id}
                                     for row in data["meeting_bookings"] for student_id in row["student_ids"]],
                "student_intakes": [{"student_id": student_id, "intake_id": row["intake_id"],
                                     "group_number": row["group_number"]}
                                    for row in data["rosters"] for student_id in row["student_ids"]],
                "rooms": data["rooms"], "lecturers": data["lecturers"],
            }.get(table, [])

            def matches(row, key, expression):
                if expression.startswith("eq."):
                    return str(row.get(key)) == expression[3:]
                if expression.startswith("in.("):
                    values = expression[4:-1].replace('"', "").split(",")
                    return str(row.get(key)) in values
                if expression.startswith("lt."):
                    left, right = row.get(key, ""), expression[3:]
                    if key.endswith("_at"):
                        left = datetime.fromisoformat(left.replace("Z", "+00:00"))
                        right = datetime.fromisoformat(right.replace("Z", "+00:00"))
                    return left < right
                if expression.startswith("gt."):
                    left, right = row.get(key, ""), expression[3:]
                    if key.endswith("_at"):
                        left = datetime.fromisoformat(left.replace("Z", "+00:00"))
                        right = datetime.fromisoformat(right.replace("Z", "+00:00"))
                    return left > right
                return True

            rows = [row for row in source if all(matches(row, key, value) for key, value in params.items()
                                                  if key not in {"select", "order", "limit", "offset"})]
            if params.get("order"):
                keys = [item.split(".")[0] for item in params["order"].split(",")]
                rows.sort(key=lambda row: tuple(str(row.get(key)) for key in keys))
            offset, limit = int(params.get("offset", "0")), int(params.get("limit", "500"))
            rows = rows[offset:offset + limit]
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(rows).encode())

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
