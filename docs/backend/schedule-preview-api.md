# Step 9: generation preview API and test page

Implemented and verified locally: 10 November 2026. **Read-only; direct localhost access in development only.**

The user postponed step 8 (timetable quality optimization), requested implementation plus a simple service-hosted page, then confirmed selected-intake/group generation and local development with authentication deferred. This supersedes the initial whole-week default. This implementation builds on the [weekly snapshot loader](scheduling-data-loader.md) and [CP-SAT feasibility solver](cp-sat-scheduling.md). Track decisions and completion in [the backend record](agents.md) and [the development checklist](../../task_hayden.md).

## Aim

Make the existing engine callable through FastAPI so a developer or authorized scheduler can select a week and inspect a complete proposed timetable without building a frontend. Generating a preview does not create class sessions, reserve resources, publish a timetable, or modify teaching occurrences.

The result satisfies compulsory scheduling rules against its captured input. With step 8 postponed, it does not minimize student gaps, lecturer gaps, or room usage. A valid result may therefore contain long gaps. Preserve the accepted opening hours, arbitrary start times, and room compatibility rules.

## Request and scope

`POST /api/schedules/generate`

```json
{
  "week_start": "2026-11-16",
  "intake_id": "00000000-0000-0000-0000-000000000001",
  "group_number": 1
}
```

The date and intake ID are illustrative; replace the intake ID with an actual database UUID. Require an exact Monday date and an intake UUID; reject unrecognized request fields. `group_number` is optional: omit it or use null for all groups in that intake, or supply a positive integer to select one group. Strings, booleans, fractions, zero and negative group numbers are rejected. Interpret the week in the configured campus timezone. Fetch actual teaching requirements and availability from the database; the caller supplies no lecturer, student roster, duration, room inventory, or booking exclusions.

Use the server's configured solver budget, worker count, and seed initially. This keeps the first contract small and prevents callers from requesting unbounded computation. Client-selectable options can be added deliberately later.

**Implemented scope:** jointly schedule only pending occurrences for the selected intake and optional group targeting that week. Already booked classes, reservations, and meetings from every intake/group remain fixed constraints with their complete student attendance sets. Cancelled occurrences stay excluded. Unscheduled demand outside the selected scope is not assigned or treated as a reservation; separate unsaved previews can overlap until trusted saving is implemented.

The backend reads and validates the complete week's source data through several direct PostgREST table/view requests before projecting requirements to the selected scope. Malformed source data outside the selected scope can still reject loading; scoped data loading is not implemented. The requests do not share a transaction snapshot. The API does not add intake/group existence queries: a syntactically valid selection without pending demand returns `NO_PENDING_REQUIREMENTS`, including a valid-looking unknown ID/group. The page accepts database IDs directly rather than introducing a catalog endpoint.

## Implemented execution flow

1. Validate the exact date string, Monday boundary, and absence of extra fields; apply development access checks before loading scheduling data.
2. Have the backend fetch weekly occurrences, overlapping class/meeting bookings, student memberships, rooms, and referenced lecturers directly from the existing Supabase tables/views. Validate and assemble the solver input, then keep only selected requirements while preserving all fixed bookings, attendance sets, rooms, and opening windows. Derive a scope-bound revision from the collected content, intake ID, and optional group; even empty selections have distinct revisions.
3. Run the existing synchronous solver in an AnyIO worker so CPU work does not occupy the asynchronous request handler. Pass configured solver settings explicitly. One capacity slot covers the full load/solve/verify operation per process; further requests receive 429 with `Retry-After: 2`. Scoped cancellation is shielded while work finishes.
4. Reuse the solver's complete-result and conflict verification. An internal verification failure must never become a successful preview.
5. Return a typed response with safe diagnostics. Keep the operation read-only and document it in FastAPI `/docs`.

One request returns its result; there is no background-job queue or polling API. The default search budget is 10 seconds; database loading, model construction, and result verification add to total request time. This is not a guaranteed 10-second HTTP deadline. Per-process capacity does not coordinate multiple server processes or reserve booking resources. A durable job workflow can be introduced if realistic workloads require it.

## Response contract

| Field | Meaning |
| --- | --- |
| `week_start`, `timezone` | The requested week and configured campus timezone |
| `status`, `has_solution` | Accurate solver outcome and whether complete assignments exist |
| `snapshot_revision` | Fingerprint binding the full source revision to the selected intake and optional group |
| `required_count` | Number of pending occurrences included in generation |
| `placements` | Occurrence, section, lecturer, room and intake IDs, group number, UTC start/end, student count, course code/name/type, room name/building |
| `diagnostics`, `candidate_failures` | Structured explanations where available, without private attendee lists |
| `statistics` | Actual search options, elapsed/search time, and solver statistics |
| `quality_optimized` | Explicitly `false` while step 8 is postponed |
| `quality` | `null` until meaningful quality measurements are implemented |
| `scope`, `intake_id`, `group_number` | `intake` or `intake_group`, selected intake UUID and optional group number |

Placement instants retain the engine's UTC representation alongside the campus timezone for display. The raw snapshot, student UUID sets, server credentials, and provider error bodies are excluded. Course and room labels come from the existing snapshot, without extra provider calls. Lecturer and intake display names are not loaded; the page shows their IDs. Preview results, handled errors, and page assets use `Cache-Control: no-store`.

`OPTIMAL`/`FEASIBLE` provide the complete requested pending set. With the current zero-objective model, `OPTIMAL` does not mean gaps or room usage have been optimized. `INFEASIBLE` indicates no complete placement exists for the captured constraints; `UNKNOWN` means the search did not establish a complete result or impossibility. `NO_PENDING_REQUIREMENTS` is an explicit empty outcome. Never return a partial schedule as success. Diagnostics are not promised to identify a minimum conflicting set.

| HTTP | Meaning |
| --- | --- |
| 200 | Complete preview, infeasible, unresolved search, or no pending demand; inspect `status` and `has_solution` |
| 422 | Invalid request/date/Monday/extra fields; standard FastAPI validation details |
| 403 / 404 | Direct local access checks failed / development tools disabled outside `development` |
| 429 | `GENERATION_BUSY`; another request occupies this process's generation slot |
| 503 | `DATABASE_NOT_CONFIGURED` |
| 504 | `DATABASE_TIMEOUT` |
| 502 | `DATABASE_UNAVAILABLE` for direct table/view read failures, or a safe loader data code |
| 500 | `MODEL_INVALID` or `GENERATION_FAILED`; no assignments are returned |

Non-validation errors have the shape `{"detail":{"code":"GENERATION_BUSY","message":"...","request_id":"..."}}`. Generation responses also carry `X-Request-ID`, including standard FastAPI validation errors. The page displays the ID for lookup in console traces or `logs/scheduling.log`. See [scheduling logging and database-read diagnosis](scheduling-logging.md). Error text never reflects raw provider responses, exception bodies, or rosters. Interactive request/response models and errors are available at `/docs`; the reusable generated contract is `/openapi.json`.

## Preview lifetime and saving boundary

The draft is returned directly without a database preview table, cache, or retrieval endpoint. It is a point-in-time result: another booking or roster change can make it stale immediately. The input revision supports later comparison but does not lock resources or authorize saving.

**Update, 11 November 2026 (step 10):** saving is implemented as `POST /api/schedules/save`; see [timetable saving](timetable-saving.md). The user chose no stored draft: the page sends back the preview it shows, and the server trusts only each placement's occurrence, room and start. It re-reads the week, requires the same scope-bound revision, revalidates every class and their mutual clashes, then writes all rows in one insert. Leaving the page still discards an unsaved preview. Full database-transactional revalidation (a database function) was deliberately deferred; the remaining race with writers outside this backend is recorded there.

## Local access and test page

The API, page and its JS/CSS require `app.environment` exactly `development`, a loopback client peer and localhost/loopback Host, an approved Origin if supplied, and no `Forwarded` or relevant `X-Forwarded-*` headers. Same-origin requests and configured CORS origins are accepted. This rejects remote/reverse-proxy access; do not remove these checks to publish an unauthenticated campus-wide endpoint. Administrator authentication remains future work. CORS permits POST for configured origins but does not authorize access.

Start the existing FastAPI service from the repository root:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

Open **http://127.0.0.1:8000/admin/development/scheduling-test-hayden** (moved under `/admin` on 12 November 2026; an admin login is now required, see [login](login.md)). No Vue build or extra page framework is required. Select a Monday, enter an intake UUID and optionally a group number, then click Generate preview. Leaving the group blank includes all groups in that intake. The page sends the selected scope to the same service, displays loading/errors, and renders new proposed classes in the response's campus timezone, including fractional seconds. It also shows the selected scope, status/counts, diagnostics, revision, and expandable raw JSON. Existing bookings remain constraints and are not included as new rows. Labels are rendered as text to avoid interpreting database content as HTML. The HTML enforces a self-only content policy.

If startup fails with Windows socket error 10048, check whether a previous service already owns the address before starting another instance:

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen | Select-Object LocalAddress, LocalPort, OwningProcess
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

Use the existing healthy service, or identify and stop your previous development process before restarting it in your terminal. Do not stop an unidentified listener. Error 10013 can also result from another listener holding exclusive address access, so its permission wording alone does not establish a firewall or privilege problem; see [Microsoft's socket error definitions](https://learn.microsoft.com/en-us/windows/win32/winsock/windows-sockets-error-codes-2). On 10 November 2026 the reported startup failures were investigated: the listener was the development service previously started during this work, and health returned `ok`. No permission or firewall change was needed to establish the cause; the first failed bind was not separately reproduced.

Live use needs the server-only Supabase settings, teaching plans/occurrences, roster/resource data, and the existing teaching-requirement migration/views. The backend reads those existing tables and views directly; it does not require `202611100003_scheduling_snapshot.sql`. Missing or invalid inputs are reported; the page does not create data or apply migrations. The known broken local virtual-environment base interpreter can be replaced with the existing ignored `.python-tools/runtime/python.exe` for this workspace; restore/recreate the normal virtual environment for a portable setup.

## Verification and reproducible UI checks

- **47 focused logging/API tests passed**, including scoped generation and the original transport/privacy/error/access/concurrency guarantees, plus request correlation, safe error classification, and privacy-preserving console/file logging.
- **248 full backend tests passed, 1 optional simulation test skipped**, in 99.50 seconds. One existing Starlette/httpx deprecation warning remains.
- **12 Node/jsdom checks passed**, including the served page making a real intake-scoped HTTP request to a synthetic solver service, rendering a valid result followed by an empty week, and displaying classified errors with request IDs.
- Native browser-app access approval previously timed out. These are DOM/HTTP checks, not a visual browser layout or browser security-policy verification. On 10 November, live RPC checks confirmed 404/PGRST202 for the now-unused RPC. The 11 November direct-table loader has not been run against hosted Supabase, so hosted permissions/behavior remain unverified. No hosted migration, grant, or booking was changed. See [the logging diagnosis](scheduling-logging.md).

Run the backend tests with a working project Python environment:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_schedule_preview.py -q
.\.venv\Scripts\python.exe -m pytest backend/tests -q
```

For isolated page tests, install jsdom locally (ignored tooling, no frontend dependency) and run the synthetic UI QA service in one terminal. This requires the same `.sql-tools/node_modules/@electric-sql/pglite` tooling as existing snapshot integration tests:

```powershell
npm.cmd install --prefix .sql-tools/ui-test --no-save --no-package-lock jsdom@26
.\.venv\Scripts\python.exe -m backend.tests.serve_schedule_preview
```

In another terminal:

```powershell
$env:NODE_PATH = (Join-Path (Get-Location).Path '.sql-tools/ui-test/node_modules')
$env:SCHEDULING_UI_URL = 'http://127.0.0.1:8001/admin/development/scheduling-test-hayden'
node --test backend/tests/schedule-preview-ui.test.cjs
Remove-Item Env:SCHEDULING_UI_URL
Remove-Item Env:NODE_PATH
```

The QA service uses synthetic PostgreSQL output and isolated credentials. Week 2026-11-09 contains pending demand for example intake `00000000-0000-0000-0000-000000000001`, group 1; other selected weeks are modeled as empty. It never points to the hosted project. Stop this temporary service after testing. Without `SCHEDULING_UI_URL`, eleven DOM cases run and the served-page HTTP case is skipped.

Completion: a caller can generate and inspect a valid complete draft through the API/page with accurate failure outcomes while actual bookings remain unchanged. Saving was added in step 10 ([timetable saving](timetable-saving.md)); quality optimization remains postponed.
