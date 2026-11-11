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
  app/scheduling/     Calendar, weekly requirements, validated engine input loader
  tests/              Backend integration checks
docs/backend/         Backend decisions, implementation notes and progress
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

- `Config/config.json` is required at backend startup and remains tracked by Git. It holds app branding, environment label, allowed development origins, Supabase environment variable names, check table, timeout, and scheduling calendar rules. Invalid/missing settings stop startup with a validation error. Restart the backend after edits.
- `.env` contains the actual Supabase URL and key. Existing environment variables take precedence. `.env` is ignored; `.env.example` is tracked. Never store keys in tracked configuration or `VITE_*` variables. The browser only receives the three public fields under `app`.
- `Config/preference.json` is an ignored `{}` placeholder. It is deliberately not read, written, or exposed by the app. Git clones will not contain it; future preference support can create it when needed.
- The compiled index/assets and the explicit local-development scheduling test page are served. The Config directory and `.env` are not public web files.

## Teaching calendar

The `scheduling` section of `Config/config.json` defines the timezone, weekday opening hours, and optional `closed_dates` (`YYYY-MM-DD`). Initial hours are Monday–Friday, **08:30–18:00**, in `Asia/Kuala_Lumpur`. Omitted weekdays are closed; change or add weekday entries to configure teaching days and different daily hours. Opening and closing times use 24-hour `HH:MM` format, with opening earlier than closing on the same day.

Classes may start at any time, with no fixed start-time interval or mandatory breaks. The full positive-duration class must fit inside one opening window. For example, 09:17–10:47 is permitted, while 17:00–18:30 is outside the initial hours. An explicit closed date overrides weekday opening hours; no public holidays are imported automatically.

`TeachingCalendar` in `backend/app/scheduling/calendar.py` accepts timezone-aware start/end timestamps and checks calendar eligibility. FastAPI initializes it as `app.state.teaching_calendar`. It does not yet check resource conflicts or generate schedules. Install the updated backend requirements for the timezone data needed on Windows.

See [backend progress and decisions](docs/backend/agents.md), [calendar details](docs/backend/scheduling-calendar.md), and the [development checklist](task_hayden.md).

## Repeating teaching requirements

Apply [the teaching-requirement migration](supabase/migrations/202611100001_teaching_requirements.sql) once after the existing database setup. It adds weekly plans for class sections and creates stable occurrences for a specified number of weeks. Lecture and lab sections can have separate plans, durations, and lecturers. Existing bookings are preserved without guessing which requirement they belong to.

The internal `load_weekly_requirements` function reads the selected target week's requirements from `teaching_occurrence_details`, including explicit make-up requirements. It can return only lessons still needing placement. No schedule-generation or plan-management API is introduced in this step.

See [teaching-plan setup and behavior](docs/backend/weekly-teaching-plans.md). The migration is verified locally; applying it to a hosted project and entering actual teaching periods remain setup actions.

## Scheduling input loader

Apply [the snapshot migration](supabase/migrations/202611100003_scheduling_snapshot.sql) after the teaching-requirement migration. The internal `load_scheduling_snapshot` function then reads one consistent week's requirements, unique student rosters, lecturers, rooms, and overlapping bookings through a read-only server-only database function. It adds configured opening windows and returns immutable input with a content fingerprint for later scheduling work.

Both the loader and older weekly reader support views with or without the removed legacy section room-type field. Configured compatibility rules are captured for booking validation. See [loader setup, validation, and verification](docs/backend/scheduling-data-loader.md).

## Booking validation

`BookingValidator` checks an occurrence, aware start time, and room against the loaded snapshot. It derives the end time, validates opening hours and room activity/capacity/type, and checks lecturer, student, and room overlaps. Results contain structured reasons and conflicting booking references. Reschedule mode excludes only the matching original class booking.

Configure `scheduling.room_compatibility`: lectures use classrooms/auditoriums; tutorials and labs use classrooms/labs. The initial `others` mapping is empty and requires explicit configuration before placement. Policy is part of the snapshot fingerprint; the legacy section room-type field does not override it. No new migration is required for this step.

Validation is internal and read-only. See [validator usage and verification](docs/backend/booking-validation.md).

## Candidate start ranges

`CandidateGenerator` finds complete room-specific ranges of valid starts for a lesson, using the same lifecycle, room, and booking-conflict rules as the validator. It subtracts fixed occupied periods from teaching windows and preserves exact duration and fractional-second boundaries. For a two-hour class in a free window from 08:30 to 12:00, the valid start range is 08:30–10:00 inclusive.

Generate one occurrence or every pending occurrence from an existing snapshot. Results include diagnostics when rooms or time ranges are unavailable; candidate generation does not reserve resources or choose a joint timetable. See [candidate generation and verification](docs/backend/candidate-generation.md).

## Joint timetable generation

`solve_weekly_schedule(snapshot, settings.scheduling.solver)` uses OR-Tools CP-SAT to assign a room and start to every pending lesson together. It enforces clashes for shared rooms, lecturers, and students across intakes, preserves fixed bookings, and verifies the complete result before returning it. Time is encoded in exact relative microseconds, without preset teaching slots.

Install updated backend requirements for OR-Tools. Configure `scheduling.solver` for search time (default 10 seconds), worker count (default 1), and random seed (default 0). Results distinguish complete solutions, proven infeasibility, unresolved search, invalid models, and an empty pending week. No partial timetable is returned as complete.

This engine produces a feasibility draft. Quality objectives are postponed; step 9 now exposes local preview generation. Authorized booking writes remain step 10. No new database migration is required for these computation/API steps. See [solver setup, usage, statuses, and verification](docs/backend/cp-sat-scheduling.md).

## Scheduling test page

With FastAPI running, open **http://127.0.0.1:8000/development/scheduling-test-hayden**. Select a Monday, enter the intake's database UUID and optionally a group number. Generate all pending classes for that intake, or only that group. The page sends a request to the same API and displays proposed classes in campus-local time, readable course/room labels, selected scope, solver outcome, diagnostics, and raw JSON. Other intakes' existing bookings remain fixed constraints. It works without building Vue.

This is a read-only local-development tool: no bookings are saved and quality optimization is disabled. The API/page require `app.environment=development` and a direct localhost connection; remote/proxy access is rejected until authenticated access is implemented. Live generation requires configured Supabase access and the earlier teaching-plan/snapshot migrations and data. See [API contract, setup, and test evidence](docs/backend/schedule-preview-api.md).

Scheduling requests now have a displayed `X-Request-ID` and safe JSON traces in the backend terminal and ignored `logs/scheduling.log`. Restart the backend to load logging changes, then watch with `Get-Content .\logs\scheduling.log -Tail 50 -Wait`. Provider `PGRST202` is reported as `SCHEDULING_RPC_NOT_FOUND`, with migration/cache guidance. See [logging and database setup diagnosis](docs/backend/scheduling-logging.md).

## API contract

| Method / path | Result |
| --- | --- |
| `GET /api/health` | `200`: backend liveness, independent of Supabase |
| `GET /api/config` | `200`: public `name`, `description`, `environment` |
| `GET /api/health/database` | `200`: `connected`; `503`: `not_configured`, `error`, or `timeout` |
| `POST /api/schedules/generate` | Development-only preview; required `week_start`, `intake_id` (UUID), optional positive integer `group_number`; no booking writes |
| `GET /development/scheduling-test-hayden` | Development-only page for requesting and reviewing generated schedules |
| `GET /docs` | Interactive OpenAPI reference |
| `GET /openapi.json` | Generated, reusable API contract |

Database health results include `status`, a safe `message`, UTC `checked_at`, and `latency_ms` (populated on success). Missing credentials, rejected access, missing table, upstream failure, timeout and invalid responses have distinct safe messages. A successful health check verifies a read via the Supabase Data API. Scheduling previews expose the existing engine through a guarded development endpoint; administrator authentication, booking writes, and preference persistence remain future work.

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
