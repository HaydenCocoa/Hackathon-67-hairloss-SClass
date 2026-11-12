# Scheduling logs and database-read diagnosis

Implemented on 10–11 November 2026. See the [preview API](schedule-preview-api.md), [backend record](agents.md), and [backend scheduling-data loader](scheduling-data-loader.md).

## Current data-loading path

The preview backend now reads the weekly occurrence view, overlapping booking view/tables, memberships, rooms, and lecturer IDs directly through PostgREST. It no longer calls `public.load_scheduling_data`; the previous `PGRST202` error for that RPC therefore no longer blocks the new code path. The historical error confirmed that the old RPC was unavailable through the schema cache, but it did not establish whether the migration was absent or the cache/signature was stale.

The direct reader still requires the existing table/view schema and server permissions. Check that the step 2 teaching-requirement migration is applied and that the configured project exposes the required views/tables to its server key. The old [snapshot RPC migration](../../supabase/migrations/202611100003_scheduling_snapshot.sql) is retained for history but is no longer required for preview generation.

## Viewing and correlating logs

Restart the backend after pulling these changes; an already-running non-reloading process still uses old code. Start from the project root with the Python environment available in this workspace:

```powershell
.\.python-tools\runtime\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

If the service is already running in your terminal, stop it with Ctrl+C first. Do not launch a second instance on the same port.

Scheduling traces appear as JSON lines in the backend terminal and `logs/scheduling.log`. Watch the file from another terminal:

```powershell
Get-Content .\logs\scheduling.log -Tail 50 -Wait
```

Generate a preview. The page displays a server-generated request ID. Find all events for it in the active or rotated log files:

```powershell
Select-String -Path .\logs\scheduling.log* -SimpleMatch 'paste-request-id-here'
```

Look for `snapshot_query_started`, `snapshot_query_completed`, or `snapshot_query_failed`. The `stage` field identifies the fixed part of the loader: requirements, class bookings, occurrence links, meetings, meeting attendees, group memberships, rooms, or lecturers. Successful reads include a row count. A successful preview continues with `snapshot_loaded`, `solver_started`, and `solver_completed`.

The API returns `X-Request-ID` for generation requests, including validation errors, access rejections, and busy responses. Since 12 November 2026 the admin rescheduling endpoints (`/api/admin/timetable/{id}/availability` and `/reschedule`) are traced the same way; the class ID in the path is not logged. CORS exposes that header to approved clients. Structured errors also include `detail.request_id`. The server creates the ID; it does not trust a caller-supplied ID.

## Privacy and limits

Logs include UTC timestamps, request IDs, fixed stage names, HTTP status, row counts, durations, and safe exception type/frame details. They do not include request payloads, SQL parameters, resource identifiers, rosters, student IDs/names, credentials, or raw provider bodies. Unexpected errors omit exception text, source lines, locals, and chained bodies.

The file rotates at 5 MiB with two backups; `logs/` is Git-ignored and not served over HTTP. Console logging continues if file creation is denied. Existing Uvicorn access logs are separate. File rotation is local and per-process; production log aggregation and multi-process rotation coordination remain future work.

Because backend loading now uses multiple PostgREST calls, a stage can fail due to a missing relation/view/column, permissions, connectivity, or timeout. The returned error stays generic and safe; correlate it with the `snapshot_query_failed` stage. Direct PostgREST reads remove the stored-function/schema-cache dependency, but still require the source schema and server-side access. The collected read set is not transactionally consistent; booking commits must perform fresh transactional validation as planned for step 10.

## Verification status

Before the 11 November backend refactor, live read-only checks observed `PGRST202` for the unused RPC. This is historical evidence only. The direct table/view loader has not yet been tested against the configured hosted project or by running the updated automated suite in this task. No hosted migration, cache notification, grant, schema, or booking was changed.
