# Step 2 — Repeating weekly teaching plans

Date: 10 November 2026 (Asia/Kuala_Lumpur).

Status: implemented locally. On 11 November, the migration and reader were updated to remove legacy room-field dependencies; this compatibility edit has not yet been verified. Hosted migration and entry of actual teaching periods are pending. No hosted database was contacted or changed.

## Accepted requirement

The user confirmed that lecture/lab teaching repeats over an identified period, such as a number of weeks. Requirements come from the database. Each week's delivery is a separate occurrence even when the teaching pattern stays the same.

## Model and decisions

Each existing class section has its own `teaching_plans` record:

| Field | Meaning |
| --- | --- |
| `section_id` | Existing intake/group and teaching component |
| `first_week_start` | Monday starting the first teaching week |
| `week_count` | Positive number of consecutive weeks |
| `occurrences_per_week` | Positive number of deliveries each week; default 1 |
| `timezone` | Timezone used to match booking dates to weeks; default `Asia/Kuala_Lumpur` |

Lecture and lab already use separate course/section records. They can have separate frequencies, durations, lecturers, and period starts. A 12-week plan with one occurrence per week creates 12 lessons. One lecture plan and one lab plan at that frequency create 24 lessons for the group.

Week numbers are relative to the plan's first Monday. Different sections/intakes can start on different Mondays. Recurrence stops after `week_count` weeks. Plans for the same section cannot overlap; adjacent periods are allowed. No production start date, number of weeks, or group plan has been guessed or inserted.

### Stable demand, separate from placement

Plan insertion creates all `week_count × occurrences_per_week` rows in `teaching_occurrences` in the same transaction, without assigning a time or room. Each has a UUID, original week, occurrence number, target week, and `required`/`cancelled` state. `(plan_id, original_week_start, occurrence_number)` is unique.

The server-only `materialize_teaching_plan(plan_id)` function can repeat expansion safely. It inserts only missing identities and never resets cancellations or moves. Plan definitions and source occurrence identities are immutable after expansion, so retries cannot silently change the teaching requirement.

Linked teaching metadata is protected to preserve the period's lecturer, course type, duration, and group. Room suitability is deliberately not stored on `class_sections`; the backend applies the configured course-to-room policy to the actual room inventory. Changing an already planned offering's lecturer or curriculum requires a deliberate future revision/versioning workflow; silently rewriting historical requirements is not supported. Because offerings are shared, protection applies while any plan remains attached, including an elapsed plan.

### Bookings, cancellation, and make-up demand

`class_sessions.occurrence_id` is nullable for existing bookings and unique when present. A composite foreign key ensures that the booking and occurrence belong to the same section. One persistent booking row is reused for a lesson's later replacement.

- A required occurrence without a scheduled booking needs placement.
- A scheduled linked booking satisfies that occurrence; it is excluded from outstanding demand.
- Cancelling a linked booking marks its requirement cancelled. Re-expanding the plan does not recreate it.
- A requirement can also be cancelled before a booking exists.
- Requesting a make-up is explicit: reopen the same requirement and choose its target week. Its UUID and original week are retained.
- Moving a scheduled booking updates its occurrence's target week using the plan timezone. Make-ups can be outside the original period under the current model.
- Linked bookings and occurrence identities cannot be deleted or detached silently; cancellation preserves them.

Existing sessions remain intact and unlinked. The migration cannot infer which required lesson they satisfy. Reconcile them explicitly before generating bookings for an overlapping period, or the scheduler will see the legacy booking as occupied time and the new requirement as still outstanding.

These triggers maintain identity and lifecycle integrity. They do not provide authorized lecturer operations, conflict checking, or automatic audit history; those remain later milestones.

### Weekly reading

`teaching_occurrence_details` joins demand to course duration/type, section/group, lecturer, and any linked booking. It includes original week, target week, plan-relative week number, booking state, and `needs_scheduling`.

`backend/app/scheduling/requirements.py` adds:

- `TeachingPlanInput`: validates section UUID, Monday start, positive integer counts, and timezone before a future admin workflow saves a plan.
- `TeachingOccurrence`: typed representation of the database view.
- `load_weekly_requirements(db, week_start, pending_only=False)`: internal async reader using the existing server-side Supabase HTTP client. Set `pending_only=True` to read only outstanding requirements.

The reader filters by target week, so explicit make-ups appear in their selected week. It orders and paginates until an empty page, even if the provider's row cap is lower than requested. Duplicate pages, wrong-week data, malformed rows, missing views, and timeouts fail explicitly. Empty demand is returned only after a successful empty response.

Multiple HTTP pages are not a transactionally consistent snapshot under concurrent writes. Full scheduling snapshot/revision handling belongs to step 4 and commit revalidation. No public plan-management or generation endpoint is added in step 2.

## Setup and usage

1. Apply the existing base schema, or the existing membership/age upgrades as appropriate.
2. Run the entire `supabase/migrations/202611100001_teaching_requirements.sql` file **once** as `postgres` in the intended Supabase SQL Editor. Both new and existing databases need this migration; do not rerun `schema.sql` on an existing database. The migration works whether `class_sections.required_room_type` is still present or was already removed by `202611100002_remove_required_room_type.sql`.
3. Identify an existing lecture or lab section and enter its actual first week, duration in weeks, and weekly count.

Illustrative insert; replace the placeholder with a real section UUID:

```sql
insert into public.teaching_plans
  (section_id, first_week_start, week_count, occurrences_per_week, timezone)
values
  ('<existing-section-uuid>'::uuid, date '2026-11-09', 12, 1, 'Asia/Kuala_Lumpur');
```

Read requirements from the database:

```sql
select occurrence_id, course_code, course_type, group_number,
       duration_minutes, lecturer_id, original_week_start,
       target_week_start, booking_status, needs_scheduling
from public.teaching_occurrence_details
where target_week_start = date '2026-11-09'
order by occurrence_id;
```

Add `and needs_scheduling` to return only outstanding requirements. Inside an authorized backend workflow:

```python
from datetime import date
from backend.app.scheduling.requirements import load_weekly_requirements
from backend.app.student import Supabase

db = Supabase(settings.supabase, http_client)
pending = await load_weekly_requirements(db, date(2026, 11, 9), pending_only=True)
```

App users have read-only access under existing section permissions; anonymous access is denied. Table writes and materialization execution are not granted to app users, including identities in the `admins` table. Use the SQL Editor or a trusted server operation. All relevant writes participate in the existing READ COMMITTED configuration lock; this is not complete booking concurrency control.

## Files and verification

| File | Purpose |
| --- | --- |
| `supabase/migrations/202611100001_teaching_requirements.sql` | Additive schema, recurrence expansion, lifecycle integrity, access policies, and view |
| `backend/app/scheduling/requirements.py` | Typed plan input and paginated weekly-demand loader |
| `supabase/tests/teaching-requirements.test.cjs` | Local PostgreSQL recurrence, identity, lifecycle, legacy-data, and access checks |
| `backend/tests/test_teaching_requirements.py` | Input validation and real HTTP reader tests against a synthetic local provider |

The results below predate the 11 November room-field compatibility edit. They verify the earlier Step 2 migration/reader, not application after `required_room_type` has already been removed.

Verified results:

- **51** new teaching-requirement database checks passed.
- Existing database checks passed: **52** schema/integrity/access, **78** membership/seed/upgrade, and **20** course-seed checks (**201 total database checks**).
- Focused backend reader/input run: **16 passed**.
- Full backend suite: **59 passed, 1 skipped**, with one existing test-client deprecation warning. The skipped check requires the optional Postman simulation, which was not running.
- `git diff --check` passed, and local documentation links resolved.

PostgreSQL tests use PGlite and minimally mocked Supabase Auth. HTTP tests use the existing Supabase reader and synthetic local responses, not a hosted project. They exercise filtering, pagination, malformed data, missing migration, and timeouts. These checks do not establish live Supabase deployment, Data API schema-cache refresh, or simultaneous-transaction stress behavior.

The Postman CLI is unavailable in this environment. The existing CLI mock covers only the rooms probe; the new reader was exercised against a temporary HTTP server instead. No simulation was deployed or published, and owner-mock discovery was not performed.

The existing `.venv` points to a missing base Python executable. A project-local CPython 3.12.10 embeddable runtime from Python.org used the existing packages for verification; its archive MD5 matched the release page. Ignored `.python-tools/` contains this temporary tooling, not a production Python upgrade. PostgreSQL tooling is in ignored `.sql-tools/`.

With a working project Python environment, run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
$env:NODE_PATH = Join-Path (Get-Location).Path '.sql-tools/node_modules'
node supabase/tests/schema.test.cjs
node supabase/tests/memberships.test.cjs
node supabase/tests/courses.test.cjs
node supabase/tests/teaching-requirements.test.cjs
```

For this task's temporary runtime, the Python command is `.\.python-tools\runtime\python.exe -m pytest backend/tests -q`.

## Remaining work and related proposals

- The user subsequently confirmed the existing database dataset is ready for the initial MVP; see [step 3 dataset scope](scheduling-dataset.md). Expanded scenario fixtures are deferred. The roster/resource snapshot, availability checks, candidate generation, CP-SAT, and authenticated write workflows remain future steps.
- The offering end-date proposal remains deferred; no cutoff is introduced. The accepted room policy is implemented in backend configuration. The Step 2 migration neither selects nor protects a legacy `required_room_type` field, and its occurrence view omits it.
- Explicit holiday dates remain in configuration. No automatic holiday or semester-break calendar is introduced, and calendar closures do not silently delete teaching demand.
- Arbitrary weekly count changes and additional unscheduled classes beyond the fixed plan need a future exception/revision workflow. Current per-occurrence exceptions cover explicit cancellation and target-week movement.

References: [PostgreSQL functions](https://www.postgresql.org/docs/current/sql-createfunction.html), [Supabase function permissions](https://supabase.com/docs/guides/database/functions), [PostgREST pagination](https://docs.postgrest.org/en/stable/references/api/pagination_count.html).
