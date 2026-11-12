# Migrations to apply on hosted Supabase

Written 12 November 2026, before the user runs these on the hosted project. **Nothing here has been run on hosted Supabase.** Every migration was tested only on local PostgreSQL (PGlite). Related: [backend record](agents.md#remaining-work), [database setup](../../supabase/README.md).

## 1. Check what is already applied

Run [hosted-migrations-status.sql](hosted-migrations-status.sql) in the SQL Editor. It is read-only and returns one row with `true` (already applied) or `false` for each migration below. It was checked locally on a database before and after all five migrations.

`202611100001 teaching requirements` must be `true`. The `rescheduled` and save-audit migrations stop if it is missing, and the admin reschedule fixes need the `rescheduled` migration first.

## 2. Run order

Run each file **once**, as a whole, in the SQL Editor (as `postgres`). Skip any that already show `true`. Each file has its own `begin … commit`, so a failure changes nothing.

| Order | File | Run it again? | Changes existing data? |
| --- | --- | --- | --- |
| 1 | `202611110001_admin_timetable.sql` (only if `false`) | **No:** a second run fails | No rows changed; adds columns |
| 2 | `202611100002_remove_required_room_type.sql` | Yes | **Deletes one column and its values** |
| 3 | `202611120001_class_session_rescheduled_status.sql` | Yes | No |
| 4 | `202611120002_save_audit.sql` | Yes | No |
| 5 | `202611120003_admin_reschedule_fixes.sql` | Yes | No |

Run 2 and 5 in the same session. Between them, the admin page's **Reschedule** fails with a database error, because the old function still reads the deleted column.

## 3. What each one does

### `202611110001_admin_timetable.sql`: admin timetable editing
- Adds `class_sessions.removed_at` and `removed_by`, so a cancelled class can be hidden from timetables without deleting it or its history. Only cancelled classes can be hidden.
- Recreates `class_session_details` so it leaves out hidden classes.
- Adds a trigger to `meeting_sessions`, `meeting_students` and `rooms` that takes the existing integrity lock on every write, so those writes queue briefly instead of racing timetable changes.
- Adds two functions for the admin page: `admin_reschedule_class` (replaced by #5) and `admin_remove_cancelled_class`. Only signed-in admins can use them.
- **Why:** the admin page's Timetable tab (Edit, Remove) needs it.

### `202611100002_remove_required_room_type.sql`: remove the old room-type field
- Deletes `class_sections.required_room_type`. Room suitability now comes from `scheduling.room_compatibility` in `Config/config.json` (lectures: classroom/auditorium; tutorials and labs: classroom/lab).
- Recreates `class_session_details` and `teaching_occurrence_details` without the field, keeping their access rules, and updates one teaching-plan trigger.
- Stops and undoes itself if anything else unexpected uses the column.
- **Cannot be undone:** the stored values are gone. To keep a copy, run this first. It goes in the private schema, which the API does not expose: `create table campus_private.class_sections_room_backup as select id, required_room_type from public.class_sections;`
- **After it:** `supabase/seed_courses.sql` and a fresh `schema.sql` still use the field. The user decided not to update those (12 November 2026).

### `202611120001_class_session_rescheduled_status.sql`: the `rescheduled` status
- Allows `class_sessions.status = 'rescheduled'`, meaning an active class that has been moved. It occupies its room, lecturer and students like `scheduled`, and still needs a room. Only `cancelled` frees the slot.
- Rebuilds the room/time index for both active statuses, and updates three teaching-occurrence trigger functions so they treat `rescheduled` as booked.
- **Why:** the lecturer page's **Save new time** writes `rescheduled`. **Without this migration that save is refused by the database (an error on the page).**

### `202611120002_save_audit.sql`: record who saved a timetable
- Adds `class_sessions.created_by`, the Supabase user who saved the class.
- Allows the action `create` in `schedule_changes`. A trigger writes one `create` row per class saved from the scheduling page, in the same statement, so classes and their audit rows are saved together or not at all.
- Rows inserted elsewhere (dashboard, seeds) leave `created_by` empty and get no audit row.
- After this, a class with an audit row **cannot be deleted**; cancel it instead.
- Asks the Supabase API to reload its schema.
- **Why:** the timetable save sends `created_by`. **Without this migration the save fails with `AUDIT_NOT_INSTALLED`.**

### `202611120003_admin_reschedule_fixes.sql`: fix the admin reschedule
- Replaces `admin_reschedule_class`. The new version:
  - checks room type from the course type, using the same mapping as `Config/config.json`, instead of the deleted column;
  - allows an auditorium only when no other permitted room seats the class;
  - can move `rescheduled` classes and counts them as clashes;
  - marks a moved class `rescheduled`, and records the old and new status in the audit.
- It still does **not** check opening hours or the 15-minute gap ([step 11 review](lecturer-reschedule-review.md)).
- If the room mapping in `Config/config.json` changes, change this function too.

## 4. After running

- Run the status query again: every column should be `true`.
- Try one admin reschedule and one lecturer reschedule on a sample class.
- Saving a generated timetable needs the local backend (see [Vercel deployment](vercel-deployment.md): previews and saves are local-development only).
