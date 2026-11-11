# Scheduling logs and RPC setup diagnosis

Implemented on 10 November 2026 after the development page displayed HTTP 502 with an upstream Supabase 404. See [preview API](schedule-preview-api.md) and [the main backend record](agents.md).

## Confirmed failure and limits of the diagnosis

A read-only request to the configured Supabase project returned HTTP 404 and **`PGRST202`**. The complete local API path reproduced it as `SCHEDULING_RPC_NOT_FOUND`. No snapshot was returned and no solver ran. PostgREST documents this code as a missing or stale matching function signature in the schema cache; it does not distinguish a missing migration from an outdated cache by itself. See [PostgREST error definitions](https://www.postgrest.org/en/v10/errors.html) and [schema cache documentation](https://docs.postgrest.org/en/stable/references/schema_cache.html).

The expected function is `public.load_scheduling_data(p_week_start date, p_timezone text)`, created by [the step 4 migration](../../supabase/migrations/202611100003_scheduling_snapshot.sql). Its prerequisite is [the teaching-requirement migration](../../supabase/migrations/202611100001_teaching_requirements.sql). This investigation did not apply migrations, refresh the live cache, alter grants, or write bookings. Hosted end-to-end generation remains blocked until the matching RPC is available.

## Viewing and correlating logs

Restart the backend after pulling these changes; an already-running non-reloading process will still use the old code. Start from the project root, with a working Python environment:

```powershell
.\.python-tools\runtime\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

If the service is already running in your terminal, stop it with Ctrl+C first. Do not launch a second instance on the same port. This task deliberately did not stop or replace the user's running port-8000 service.

Scheduling traces appear as JSON lines in the backend terminal and **`logs/scheduling.log`**, relative to the project root. Watch the file from another terminal:

```powershell
Get-Content .\logs\scheduling.log -Tail 50 -Wait
```

Generate again in the test page. The result or error shows a server-generated request ID. Find that request in the active log and rotated copies:

```powershell
Select-String -Path .\logs\scheduling.log* -SimpleMatch 'paste-request-id-here'
```

The API returns `X-Request-ID` for generation requests, including validation errors, access rejections, and busy responses. CORS exposes that header to approved clients. Structured errors also include `detail.request_id`. Inbound request IDs are ignored; the server creates a fresh UUID per request. Validation errors retain standard FastAPI details and use the header for correlation.

## Recorded stages and privacy

Typical successful sequence: `request_started`, `rpc_started`, `rpc_completed`, `snapshot_loaded`, `solver_started`, `solver_completed`, `request_completed`.

The reported failure yields `rpc_failed` with `provider_status=404`, `provider_code=PGRST202`, and `code=SCHEDULING_RPC_NOT_FOUND`, followed by rejection and final HTTP 502. There is no solver event. This distinguishes database setup failures from malformed scheduling input, actual infeasibility, and unresolved solver search.

Records contain UTC timestamps, levels, request IDs, named stages, HTTP/provider status, allowlisted provider codes, counts, and timing where applicable. Unexpected internal errors add exception type and stack frame file basenames, function names, and line numbers. They omit exception text, source lines, local variables, and chained exception bodies. No request bodies, raw provider messages/details/hints, URLs, keys, authorization headers, intake/student IDs, student lists, names, or complete snapshots are recorded by this logging channel. Unrecognized provider error codes are omitted, and unstructured messages sent to this logger are suppressed by its formatter.

The file rotates at 5 MiB with two backups (`scheduling.log.1` and `.2`), approximately 15 MiB total. `logs/` is ignored by Git and is not served over HTTP. Console logging continues with a safe warning if file creation is denied. Configuration is idempotent within a process, avoiding duplicate handlers when apps are created repeatedly. This is a local per-process logging facility; production log aggregation and multi-process rotation coordination remain future work. Existing Uvicorn access logging is separate.

## Actionable error categories

| API code | Meaning |
| --- | --- |
| `SCHEDULING_RPC_NOT_FOUND` | Provider `PGRST202`; matching function unavailable in the schema cache |
| `DATABASE_PERMISSION_DENIED` | Provider HTTP 401/403 or SQLSTATE 42501; check trusted key and grants |
| `DATABASE_SCHEMA_INCOMPLETE` | Known missing table/column/function SQLSTATE; check prerequisite migrations |
| `DATABASE_UNAVAILABLE` | Other safe upstream failure, without copying provider bodies |
| `DATABASE_TIMEOUT` | RPC request timed out |
| Existing loader/solver codes | Invalid snapshot, model, internal verification failure, or busy generation |

## Resolving the current database setup failure

In the intended project's Supabase SQL editor, inspect existence without modifying data:

```sql
select
  to_regclass('public.teaching_occurrences') as teaching_occurrences,
  to_regprocedure('public.load_scheduling_data(date,text)') as scheduling_rpc;
```

If the function is null, apply the missing snapshot migration after its prerequisite. Existing migrations contain non-idempotent creation statements; do not blindly rerun migrations already installed. The optional room-type removal patch is independent and should follow the project's existing setup state.

If the function exists, check its named arguments, exposed schema and server-role permissions. Refresh the Data API's schema cache in the SQL editor and retry:

```sql
NOTIFY pgrst, 'reload schema';
```

Supabase documents this refresh in [its schema-cache troubleshooting guide](https://supabase.com/kb/troubleshooting/refresh-postgrest-schema). If the request still fails, use the new request ID/provider code rather than assuming it is the same failure. The existing snapshot migration already includes a reload notification when applied.

## Verification

The focused logging/API suite passed **47 tests**. Privacy checks inject secret-looking provider bodies and internal exception messages, then verify they do not appear in responses or trace records. Other checks cover correlated success/failure/validation/access IDs, server-generated IDs, stage ordering, error classification, CORS exposure, idempotent file logging, and safe console fallback.

The full backend suite passed **248 tests, 1 optional simulation test skipped**, in 99.50 seconds, with one existing Starlette/httpx deprecation warning. No SQL source changed; standalone database suites were not rerun. Existing SQL fixtures still execute in the HTTP integration coverage.

All **12 Node/jsdom page tests passed**, including a served-page/real HTTP synthetic scheduling flow and displaying the error classification and request ID. A configured live read-only request confirmed the PGRST202 failure and generated a correlated file/console trace without returning a snapshot. These results establish tracing and the current RPC failure, not successful hosted scheduling or browser visual verification.
