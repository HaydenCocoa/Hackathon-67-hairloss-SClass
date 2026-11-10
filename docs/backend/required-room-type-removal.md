# SQL-only removal of required_room_type

Date: 10 November 2026 (Asia/Kuala_Lumpur).

The user accepted removing `class_sections.required_room_type`, deferred offering dates, and requested SQL for manual execution. No hosted execution or complete backend implementation was requested or performed.

[The complete SQL patch](../../supabase/migrations/202611100002_remove_required_room_type.sql) recreates the known timetable/occurrence views without the field, retaining security-invoker behavior and existing application-role read grants. It updates the optional teaching-plan protection function before dropping the column. It uses no CASCADE: unexpected dependencies cause rollback. Tables, bookings, actual room classification, group rules, and unrelated teaching metadata protections are preserved.

The core command alone is `alter table public.class_sections drop column if exists required_room_type;`, but existing dependent views prevent using that line alone. The full patch is transactional and can be rerun.

## Current status and remaining work

- SQL prepared and checked locally, not applied to hosted Supabase.
- `schema.sql` is unchanged because the user plans to document executed fixes manually in its final section.
- The existing course seed inserts the removed field; adapt it before reuse.
- Step 4 subsequently adapted the Python weekly reader and new snapshot loader to accept views with or without the removed field. See [loader compatibility and verification](scheduling-data-loader.md). Room-selection policy remains separate.
- Step 5 adds the user-confirmed compatibility policy and booking checks; see [booking validation](booking-validation.md). Automatic candidate/room selection, older setup/seed compatibility, and ERD updates remain follow-up work.
- The patch handles a base database without the optional teaching extension. However, an old teaching-requirement migration still references the removed field; do not apply that old migration after this patch without adapting it.
- Course-offering changes remain deferred. Calendar rules are unchanged.

## Verification

25 SQL checks passed through PostgreSQL/PGlite with mocked Supabase Auth. Coverage includes the base schema and teaching extension, preserved records and end-time calculations, view queries, absence of broken trigger references, preserved teaching metadata protection, role access, reruns, and rollback on unexpected dependencies.

These original 25 checks validate the SQL patch only; that SQL-only task did not run a backend suite or hosted tests. The later step 4 task adds reader compatibility and its own runtime verification. The older course seed still requires adaptation before reuse after removal.
