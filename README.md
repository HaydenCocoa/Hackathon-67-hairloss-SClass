# SClass MVP

A basic main menu built with **Vue + Vite**, communicating over HTTP with a **Python + FastAPI** backend. Existing SQL scripts in `supabase/` are preserved.

## Project structure

```text
Config/
  config.json         Tracked startup settings
  preference.json     Ignored empty placeholder; no preference behavior yet
backend/
  app/config.py       Startup configuration validation
  app/database.py     Read-only Supabase connectivity check
  app/main.py         HTTP endpoints and built frontend serving
  tests/              Backend integration checks
frontend/
  src/                Vue main menu, styles, HTTP client
  vite.config.js      Development proxy to FastAPI
supabase/             Existing schema, migrations and seeds
postman/              Optional local Supabase contract simulation
```

## Run locally (PowerShell)

Requires Python 3.10+ and Node.js 20.19+ or 22.12+ (Node 24 works).

From the project root:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
Copy-Item .env.example .env
```

Edit `.env` with your Supabase project URL and a **server-only secret key** (`sb_secret_...`) or legacy `service_role` key. The existing database schema denies anonymous table access, so a publishable/anon key alone will not pass this check. Credentials are optional for starting the app; without them the database card shows setup instructions when tested.

Apply [supabase/schema.sql](supabase/schema.sql) for a new database, or follow the [database upgrade instructions](supabase/README.md) for an existing database. The probe uses the existing `rooms` table and works even if it is empty. It performs `GET /rest/v1/rooms?select=id&limit=1`; it does not insert or update records, return table rows to the browser, or test scheduling logic.

Terminal 1, from the project root:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2:

```powershell
cd frontend
npm ci
npm run dev
```

Open **http://127.0.0.1:5173**. The main menu loads its display settings from FastAPI and shows backend/configuration status. Click **Test connection** to check Supabase. **Open API reference** opens FastAPI's interactive documentation.

## Serve the built app through FastAPI

```powershell
cd frontend
npm run build
cd ..
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**. FastAPI serves the compiled Vue app and API from one origin. Build before starting/restarting FastAPI so the asset mount is registered. `vite preview` is only a frontend build preview; use FastAPI for the complete built application.

## Configuration and preferences

- `Config/config.json` is required at backend startup and remains tracked by Git. It holds app branding, environment label, allowed development origins, Supabase environment variable names, check table and timeout. Invalid/missing settings stop startup with a validation error. Restart the backend after edits.
- `.env` contains the actual Supabase URL and key. Existing environment variables take precedence. `.env` is ignored; `.env.example` is tracked. Never store keys in tracked configuration or `VITE_*` variables. The browser only receives the three public fields under `app`.
- `Config/preference.json` is an ignored `{}` placeholder. It is deliberately not read, written, or exposed by the app. Git clones will not contain it; future preference support can create it when needed.
- Only the compiled index and assets are served. The Config directory and `.env` are not public web files.

## API contract

| Method / path | Result |
| --- | --- |
| `GET /api/health` | `200`: backend liveness, independent of Supabase |
| `GET /api/config` | `200`: public `name`, `description`, `environment` |
| `GET /api/health/database` | `200`: `connected`; `503`: `not_configured`, `error`, or `timeout` |
| `GET /docs` | Interactive OpenAPI reference |
| `GET /openapi.json` | Generated, reusable API contract |

Database results include `status`, a safe `message`, UTC `checked_at`, and `latency_ms` (populated on success). Missing credentials, rejected access, missing table, upstream failure, timeout and invalid responses have distinct safe messages. A successful check verifies a read via the Supabase Data API, rather than just reaching its HTTP server. This is an MVP with no authentication, scheduling operations or preference persistence.

## Verify

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest backend/tests -q
cd frontend
npm run build
```

Tests run real HTTP requests against a temporary local stand-in for Supabase. They check successful reads, credential/header handling, private response data, upstream failures, malformed responses, timeouts, missing settings and static file serving. They do not establish connectivity to your hosted project; use the menu with your `.env` for that.

Optional Postman CLI simulation (1.70+), from the project root:

```powershell
postman simulation run postman/simulations/supabase.sim.yaml --port 4010 --no-history --output ndjson
```

In another terminal:

```powershell
$env:SUPABASE_SIMULATION_URL = 'http://127.0.0.1:4010'
.\.venv\Scripts\python.exe -m pytest backend/tests -q
Remove-Item Env:SUPABASE_SIMULATION_URL
```

The optional simulation uses only synthetic credentials, models an empty table and rejected API key, and never connects to Supabase. Stop it with Ctrl+C. Provider docs: [Supabase Data API](https://supabase.com/docs/guides/api), [API keys](https://supabase.com/docs/guides/getting-started/api-keys), [FastAPI static files](https://fastapi.tiangolo.com/tutorial/static-files/), [Vite](https://vite.dev/guide/).


## Admin portal

The administrator portal provides intake CRUD and a read-only university timetable viewer. See [Admin portal setup](docs/admin-portal.md) for administrator registration, API routes, and usage.
