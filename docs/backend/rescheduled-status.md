# `rescheduled` class-session status

Date: 12 November 2026. Branch: `backend-enhancement`.

Status: implemented and verified locally (PGlite and the backend test suite). **The SQL has not been run on the hosted Supabase project**; the user runs it manually.

## Requirement

`class_sessions.status` was limited by a database CHECK constraint to `scheduled` or `cancelled`. The user asked to add `rescheduled`, used when a lecturer or admin moves a class that is scheduled.

The user considered removing the restriction entirely but chose to keep it and add one specific value. A constraint with no restriction would let typos (`Cancelled`, `canceled`) through silently. The scheduler would then treat such a class as free time, while the student and lecturer pages would show it as an active class.

## Meaning of each status

| Status | Occupies room, lecturer and students | Needs a room | Counts as booked (not outstanding demand) |
| --- | --- | --- | --- |
| `scheduled` | Yes | Yes | Yes |
| `rescheduled` | Yes | Yes | Yes |
| `cancelled` | No | No | No; the occurrence is cancelled until explicitly reopened |

`rescheduled` is an **active booking that has been moved**. The row is moved in place, so the occurrence link, booking ID and original week are preserved. Moving the same class again keeps `rescheduled`. Only `cancelled` releases a slot.

Reason: `class_sessions.occurrence_id` is unique, so a move cannot create a second row for the same occurrence. The existing lecturer endpoint already updates the row in place.

`meeting_sessions.status` is unchanged (`scheduled`, `cancelled`).

## SQL to run on Supabase

Run [supabase/migrations/202611120001_class_session_rescheduled_status.sql](../../supabase/migrations/202611120001_class_session_rescheduled_status.sql) once in the SQL Editor as `postgres`. Running it a second time is harmless.

What it does, in one transaction:

1. Checks that the step 2 migration (`202611100001_teaching_requirements.sql`) has been applied, and stops otherwise.
2. Drops every CHECK constraint on `class_sessions` that mentions `status`, whatever its name, and adds:
   - `class_sessions_status_check`: `status in ('scheduled', 'rescheduled', 'cancelled')`
   - `scheduled_class_requires_room`: `status not in ('scheduled', 'rescheduled') or room_id is not null`
3. Recreates the partial index `class_sessions_room_time_idx` for both active statuses.
4. Replaces three step 2 trigger functions so they treat `rescheduled` as active:
   - `validate_teaching_occurrence`: an occurrence cannot be cancelled, or have its target week changed, while it has an active booking.
   - `validate_occurrence_booking`: an active booking cannot be attached to a cancelled occurrence until it is explicitly reopened.
   - `sync_occurrence_booking`: moving an active booking to another week updates the occurrence's target week.

No rows are changed. Existing values are all `scheduled` or `cancelled`, so the new constraint validates immediately.

**Fresh setup order:** `schema.sql` → `202611100001_teaching_requirements.sql` → this migration. `schema.sql` already contains the new constraint and index. The step 2 migration recreates the old trigger bodies, though, so this migration must still run after it.

Check the result:

```sql
select conname, pg_get_constraintdef(oid)
from pg_constraint
where conrelid = 'public.class_sessions'::regclass and contype = 'c';
```

**Not changed:** the historical `load_scheduling_data` RPC (`202611100003_scheduling_snapshot.sql`) still filters `status = 'scheduled'`. The backend no longer calls it (it uses direct reads since 11 November). If it is ever used again, update its two filters as well.

## Backend changes

| File | Change |
| --- | --- |
| `backend/app/scheduling/requirements.py` | Adds `BookingStatus`, `ActiveBookingStatus` and `ACTIVE_BOOKING_STATUSES` in one place. `booking_status` accepts `rescheduled`. |
| `backend/app/scheduling/loader.py` | Reads class bookings with `status in (scheduled, rescheduled)`. Class bookings accept both values. The pending check and the booking-match check treat both as active. |
| `backend/app/scheduling/validator.py` | Both statuses block resources. A `rescheduled` occurrence counts as already booked (`ALREADY_SCHEDULED`) and can be moved again in reschedule mode. |
| `backend/app/lecturer.py` | `PATCH /api/lecturers/{id}/sessions/{session_id}` now writes `status: "rescheduled"` with the new time and room. It returns **409** for a cancelled class, because writing `rescheduled` would otherwise reactivate it. The timetable response sets `moved` to true for `rescheduled`, and `can_reschedule` allows both active statuses. |

Without these changes, one `rescheduled` row would have caused three failures:

- The scheduling loader would fail with `STATE_MISMATCH`, or with a validation error, for the whole week.
- The class would not block its room, lecturer or students.
- The lecturer would lose the reschedule button for that class.

Unchanged:

- Step 10 saving still writes `scheduled`.
- The student page only checks for `cancelled`, so a `rescheduled` class shows as an active class.
- The lecturer page already shows a "Rescheduled" chip when `moved` is true.
- No frontend component was edited.

## Verification (local)

- New database test [supabase/tests/rescheduled-status.test.cjs](../../supabase/tests/rescheduled-status.test.cjs): **33 checks passed**. It runs once as an upgrade from the legacy two-value schema and once on a fresh `schema.sql`. It covers the following:
  - the old constraint rejecting `rescheduled` before the patch
  - running the migration twice
  - exactly two constraints remaining
  - unchanged rows
  - the index predicate
  - rejection of `postponed` and `Rescheduled`
  - the room rule
  - a move to another week updating the target week while keeping the original week
  - no outstanding demand while booked
  - occurrence-cancel protection
  - cancelling, and the reopen requirement
- Existing database suites still pass: 52 schema, 78 membership, 20 course, 51 teaching-requirement, 25 room-removal and 32 snapshot checks.
- Backend tests:
  - 2 new loader tests passed: rescheduled bookings load and block, and the query uses `in.(...)`; cancelled bookings are not read.
  - Updated auth tests passed: an admin move sends `status: "rescheduled"`, and moving a cancelled class returns 409.
- The 2 new validator tests (blocking, and moving again) **error in the normal run**. The whole `test_booking_validator.py` file errors on an already-broken fixture that passes the removed `required_room_type` field. They passed (54 of 54) in a temporary copy with only that argument removed. The copy was deleted afterwards.
- Full backend suite: **10 failed, 196 passed, 1 skipped, 97 errors**. Compared line by line with `main`, the only differences are those 2 new validator tests. There are no regressions.
- Not verified: the migration on hosted Supabase; the lecturer reschedule against the real database; a real browser.

## Open points

- The lecturer reschedule endpoint still writes directly, without the booking validator or a `schedule_changes` audit row. This was observed before and is outside this change; it belongs to step 11.
- The stale `required_room_type` validator fixture is still unfixed.
