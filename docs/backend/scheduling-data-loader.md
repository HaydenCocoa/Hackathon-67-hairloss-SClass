# Step 4 — Scheduling-data loader

Date: 10 November 2026 (Asia/Kuala_Lumpur).

Status: complete and verified locally. No hosted migration or live database call has been performed by this task.

## Contract and decisions

- Internal entry point: `load_scheduling_snapshot(db, settings, week_start)`. The week starts on Monday in the configured campus timezone.
- Add a read-only, service-role-only database function, `load_scheduling_data(p_week_start, p_timezone)`, returning one JSON object. A STABLE function reads requirements, rosters, rooms, lecturer references, and overlapping bookings using one database snapshot. This avoids torn data across independently paginated requests.
- The wire object contains `schema_version`, selected week/timezone, horizon start/end, capture timestamp, database snapshot identifier, weekly requirements, section rosters, room inventory, lecturer identities, scheduled class bookings, and meeting bookings.
- Resolve student attendance by exact intake/group membership, deduplicated by student UUID. Never infer student conflicts from intake names alone.
- Include all target-week requirements so already-booked and cancelled occurrences remain distinguishable. Expose outstanding requirements separately to the later engine.
- Include scheduled bookings with `starts_at < horizon_end` and `ends_at > horizon_start`, even when they begin before the week. Ignore cancelled bookings. Use derived class end times and explicit meeting end times.
- Existing reservations are represented by scheduled class bookings; there is no separate reservation table. Keep them as fixed occupied intervals. Empty booking/meeting arrays are valid, and no meeting sample data is required.
- Keep room inventory metadata, including inactive rooms. Candidate selection and conflict checking remain later steps; do not silently assume every room is available.
- Return a validated, immutable engine input with aware UTC timestamps, effective daily opening windows, actual student counts, and a content fingerprint. Capture metadata is excluded from the fingerprint. A snapshot is not a booking lock; later commit logic must revalidate it.
- Reject malformed/mismatched input, duplicate identities, missing referenced resources/rosters, and pending sections without students. Empty weekly demand is valid and remains visibly empty, not a successful generated timetable.
- Support the existing view and the accepted SQL patch that removes `required_room_type`. Retain it as optional legacy metadata only; course type and actual room types remain available. Do not infer a replacement room-compatibility policy or offering cutoff.
- No public snapshot endpoint or hosted database write is introduced. Detailed student IDs are internal scheduling data and must not be logged or exposed to an unauthenticated frontend.

## Verification plan

Use local PostgreSQL tests for the function's week filtering, overlapping intervals, roster resolution, cancellation, permissions, read-only behavior, and payload completeness. Run the real backend loader over HTTP against a local stand-in for transport/failure checks. Connect the HTTP test path to real local PostgreSQL where practical, and distinguish that evidence from live Supabase verification. Do not require meeting or deliberately infeasible sample data in the hosted dataset.

## Implementation and setup

Apply `supabase/migrations/202611100003_scheduling_snapshot.sql` once, after the step 2 teaching-requirement migration. It also works after the accepted optional `202611100002_remove_required_room_type.sql` patch. The snapshot migration does not remove columns, insert sample data, or change existing bookings. It requests a PostgREST schema-cache reload after creating the function.

The function is `STABLE` and `SECURITY INVOKER`. Execute access is granted to `service_role` and revoked from `PUBLIC`, `anon`, and `authenticated`. This intentionally prevents ordinary users, including application admins, from obtaining a partial or campus-wide scheduling snapshot directly. Use it from an authorized trusted backend workflow; no new public FastAPI route is added.

`backend/app/student.py` extends the existing Supabase transport with `rpc(function, parameters)` for JSON-object responses. `backend/app/scheduling/loader.py` calls it once with:

```json
{"p_week_start": "2026-11-09", "p_timezone": "Asia/Kuala_Lumpur"}
```

The database returns a scalar JSON object rather than a row-paginated relation, so all relevant rosters/resources are captured in one request. Calendar rules are copied from validated startup settings and transformed into effective opening intervals for the selected week. Database instants and opening-window timestamps are normalized to UTC; `snapshot.timezone` and each window's `day` retain the campus calendar context.

### Internal usage

```python
from datetime import date
import httpx

from backend.app.config import load_settings
from backend.app.student import Supabase
from backend.app.scheduling.loader import load_scheduling_snapshot

settings = load_settings()
async with httpx.AsyncClient(follow_redirects=False) as http_client:
    db = Supabase(settings.supabase, http_client)
    snapshot = await load_scheduling_snapshot(db, settings.scheduling, date(2026, 11, 9))
    pending = snapshot.pending_requirements
```

Use the app's existing environment initialization and HTTP client when calling from a running backend. The standalone snippet assumes the configured database environment variables are already available; it is async function body code, not a new public endpoint or a complete command-line program.

### Engine-facing fields

| Field | Meaning |
| --- | --- |
| `week_start`, `timezone` | Selected local Monday and calendar timezone |
| `horizon_starts_at`, `horizon_ends_at` | Half-open weekly interval in UTC |
| `opening_windows` | Effective configured teaching windows after explicit closures |
| `room_rules` | Immutable course-to-room compatibility mapping captured from config in step 5 |
| `requirements` | All target-week occurrences with lecturer, duration/type, lifecycle, and student IDs/count |
| `pending_requirements` | Read-only property selecting occurrences needing placement |
| `rooms` | Inventory with capacity, actual room type, and active flag |
| `lecturers` | Referenced lecturer UUIDs; no names are needed by the engine |
| `class_bookings` | Fixed occupied intervals, including actual class student IDs |
| `meeting_bookings` | Existing occupied intervals with explicit attendance; room can be absent for online meetings |
| `captured_at`, `database_snapshot` | Read provenance |
| `revision` | SHA-256 fingerprint of effective input content and calendar windows |

Tuples, frozen models, and student-ID frozensets prevent accidental mutation. Fingerprints ignore array/set ordering and capture metadata, but change when relevant resources, rosters, requirements, bookings, or opening windows change. They help detect changed input; they do not reserve resources, provide an authorization token, or replace later transactional commit validation.

### Validation behavior

`SchedulingDataError` exposes safe `code` and `detail` attributes. Categories cover malformed snapshots, wrong horizon/timezone, duplicate IDs, missing lecturer/room/roster, mismatched intake/group, empty pending rosters, inconsistent requirement lifecycle, mismatched fixed bookings, and out-of-horizon intervals. Transport failures use the existing safe HTTP error pattern: missing function/permission/upstream error gives 502; timeout gives 504. Upstream bodies and credentials are not included in error messages.

Pending sections with zero students are treated as incomplete enrollment data. Empty rosters for cancelled or already-booked classes can still be represented. An empty week is valid input; it is not a claim that a timetable was generated. All-inactive rooms or closed teaching windows remain represented for later feasibility handling rather than being silently relaxed.

All class end times are derived in PostgreSQL using the existing course-duration view and checked against their duration in Python. Existing bookings are included according to actual overlaps, even outside teaching hours; the loader does not retroactively approve them. Actual conflict checking and placement eligibility belong to steps 5–7.

## Compatibility with room-requirement removal

The step 2 `TeachingOccurrence.required_room_type` field is now optional legacy metadata. The older weekly reader selects the fixed view's columns using `*`, then validates/types them, so it works when that legacy column is absent. The new snapshot reader also accepts either schema. It continues returning `course_type` and actual `rooms.room_type` values. Step 5 subsequently adds explicit configured compatibility rules to the captured input and fingerprint; see [booking validation](booking-validation.md). No automatic room selection occurs during loading.

The user-managed initial schema/old course seed still have their separately documented compatibility limitations after column removal. This task does not rewrite them or the previously prepared removal patch.

## Files and verification evidence

| File | Purpose |
| --- | --- |
| `supabase/migrations/202611100003_scheduling_snapshot.sql` | Read-only coherent database payload and server-only permission |
| `backend/app/scheduling/loader.py` | Typed immutable input, validation, calendar windows, and fingerprint |
| `backend/app/student.py` | Existing shared transport extended for JSON-object RPC |
| `backend/app/scheduling/requirements.py` | Legacy/new view compatibility |
| `supabase/tests/scheduling-snapshot.fixture.cjs` | Synthetic local database setup; exports the real function's JSON for HTTP tests |
| `supabase/tests/scheduling-snapshot.test.cjs` | PostgreSQL query/permission/boundary/compatibility checks |
| `backend/tests/test_scheduling_loader.py` | Real loader over HTTP using real local PostgreSQL output plus injected failure responses |
| `backend/tests/test_teaching_requirements.py` | Additional older-reader compatibility regression |

Verified results:

- New snapshot database suite: **32 checks passed**.
- Focused backend loader and weekly-reader suites: **53 passed**.
- Full backend suite: **96 passed, 1 skipped**, in 54.96 seconds. The skipped check requires the optional Postman simulation. One existing test-client deprecation warning remains.
- All database suites passed: **52** schema, **78** membership/upgrade, **20** course-seed, **51** teaching-requirement, **25** room-removal, and **32** snapshot checks, totaling **258 checks**.
- `git diff --check` and local documentation-link checks passed.

The backend integration tests exercise actual PostgreSQL output over a local HTTP stand-in for the Supabase RPC route, including loading the function after the room-removal patch. SQL tests also recreate the views after a previous snapshot read. They do not run a full PostgREST server, contact hosted Supabase, or stress-test concurrent transactions.

Postman CLI is unavailable, so the existing rooms-only CLI mock is not used for this new path. Owner-mock discovery and simulation publication were not performed. The controlled temporary HTTP server records the request path, parameters, and synthetic authentication headers for assertions; provider-shape and failure variants are explicit in the tests.

Run with a working backend Python environment and the local PGlite package installed:

```powershell
npm install --prefix .sql-tools --no-save --package-lock=false @electric-sql/pglite
.\.venv\Scripts\python.exe -m pytest backend/tests -q
$env:NODE_PATH = Join-Path (Get-Location).Path '.sql-tools/node_modules'
node supabase/tests/scheduling-snapshot.test.cjs
```

This workspace currently uses the previously established ignored `.python-tools/runtime/python.exe` for tests because `.venv` still points to a missing base interpreter. Loader integration tests explicitly skip if Node/PGlite tooling is absent; it was present for this task's executed checks.

## Remaining boundaries

- Apply the migration to the intended project and verify live server-key access separately. Dataset readiness was confirmed by the user in step 3; it is not a live verification performed here.
- The database read is consistent at capture time, but later writes can change it. Recompute/revalidate within the later booking transaction.
- Legacy bookings remain unlinked unless deliberately reconciled. The loader includes their occupied time without assuming they satisfy an occurrence.
- No roster names or student codes are retrieved; internal student UUIDs must still remain in authorized backend workflows.
- No solver, room-policy decision, booking write, notification, automatic holiday feed, or offering end-date rule is added.

References: [PostgreSQL STABLE function snapshots](https://www.postgresql.org/docs/current/xfunc-volatility.html), [PostgREST RPC](https://docs.postgrest.org/en/stable/references/api/functions.html).
