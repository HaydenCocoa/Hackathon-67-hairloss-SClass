# Step 4 — Backend scheduling-data loader

Date: 11 November 2026 (Asia/Kuala_Lumpur).

Status: backend query implementation complete; verification not run in this task. Hosted database connectivity and schema permissions remain unverified.

## Decision and contract

The backend owns scheduling data access and assembles the immutable engine input. It reads the existing Supabase tables and views through PostgREST `GET` requests. Schedule generation no longer calls `public.load_scheduling_data` or relies on the step 4 snapshot RPC migration.

The internal entry point remains `load_scheduling_snapshot(db, settings, week_start)`. It reads the requested Monday's occurrences, overlapping scheduled class and meeting bookings, linked occurrence IDs, group memberships, rooms, and referenced lecturer IDs. Reads are paginated at 500 rows with stable ordering. The backend resolves rosters by exact intake/group membership, builds meeting attendance, validates cross-references, derives the campus-week opening windows, and computes the content fingerprint.

The source schema is still a required contract: the backend reads `teaching_occurrence_details` and `class_session_details`, as well as `class_sessions`, `meeting_sessions`, `meeting_students`, `student_intakes`, `rooms`, and `lecturers`. The teaching-occurrence view comes from the step 2 migration. The old `required_room_type` column is not selected. A missing table/view, column, permission, or wrong project configuration will still cause a safe database error; this refactor removes the RPC function/cache dependency, not database schema requirements.

## Data selection

- Include every target-week teaching occurrence, not only pending rows. Preserve occurrence identity, original week, target week, booking linkage, and cancellation state.
- Include every scheduled class and meeting whose interval overlaps the local week converted to UTC. Class end times come from `class_session_details`; meetings use stored end times. Cancelled bookings do not block generation.
- Resolve group membership by the exact pair `(intake_id, group_number)`. This preserves shared-student conflicts across intakes without loading names or student codes.
- Include all rooms, including inactive inventory, and only lecturer identities referenced by requirements/bookings. The engine applies suitability and availability rules afterward.
- Keep existing bookings across all intakes/groups fixed when previewing a selected intake/group.
- Paginate all provider lists, and fail clearly on malformed, incomplete, duplicated, mismatched, or impossible references instead of treating them as an empty schedule.

## Consistency boundary

Unlike the previous SQL function, PostgREST table/view reads are separate HTTP requests and do not share one PostgreSQL MVCC snapshot. `captured_at` records when the backend finished assembling the read set; the internal `database_snapshot` value is now a PostgREST capture marker, not a database snapshot ID. The content revision fingerprints the collected scheduling inputs but cannot detect a change that happens midway through the reads if that change leaves the final collected values internally consistent.

This is acceptable for the local read-only preview MVP. A preview is not a lock or commit authorization. Step 10 must re-read and validate all affected rows transactionally before any booking write; if a strict coherent read becomes necessary earlier, the system will need a transaction-capable backend database connection or another server-side snapshot mechanism.

## Logging and safety

The loader emits safe `snapshot_query_started`, `snapshot_query_completed`, and `snapshot_query_failed` events by fixed stage name, with row counts and exception types only. It never logs query parameters, resource identifiers, request bodies, roster contents, credentials, or raw provider bodies. See [scheduling logging](scheduling-logging.md).

Student UUIDs remain internal solver data. They are not returned to the development page or written to logs. The development API remains loopback-only and read-only.

## Migration history

The file [`202611100003_scheduling_snapshot.sql`](../../supabase/migrations/202611100003_scheduling_snapshot.sql) is retained as historical migration work. The backend no longer needs that function; do not apply it solely to enable the new loader. If it was previously applied, leaving the unused function in place is harmless. The step 2 teaching-requirement migration and its view are still needed for database-backed weekly requirements.

## Files

| File | Purpose |
| --- | --- |
| `backend/app/scheduling/loader.py` | Direct PostgREST reads, pagination, roster resolution, validation, calendar windows, and fingerprint |
| `backend/app/student.py` | Shared server-only Supabase table/view transport |
| `backend/app/scheduling/preview.py` | Invokes backend loader before solving |
| `backend/tests/test_scheduling_loader.py` | Local HTTP provider fixture for table/view reads |
| `backend/tests/test_schedule_preview.py` | Preview flow, scope, and safe error coverage |

## Verification

No tests or live Supabase calls were run for the 11 November refactor. The prior tests verified the old RPC-backed implementation and do not verify this change. The updated test fixtures now model direct read requests, but their results are pending a future authorized verification run. No database migration, hosted data, booking, or schema was changed by this code refactor.
