# Supabase database setup

1. Open the intended development project in the Supabase dashboard.
2. Open **SQL Editor**, create a query, and paste the entire contents of `schema.sql`.
3. Run it as the default `postgres` role. This requires PostgreSQL 15 or later.
4. Inspect the thirteen application tables in **Table Editor** and the relationships in **Database > Schema Visualizer**. `auth.users` already exists and is not created by this script.
5. Query `public.class_session_details` when you need class end times.

This is a one-time initial setup, not an upgrade or reset script. It preserves the rooms table from the previous tutorial when that table has its original definition. If other application tables already exist, the setup stops and rolls back; do not delete existing tables to bypass an error. After an SQL Editor error in a manually retained transaction, run `rollback;` before retrying a corrected script.

## Upgrade an existing single-intake database

If you already ran the previous schema, run [migrations/202611080001_student_intake_memberships.sql](migrations/202611080001_student_intake_memberships.sql) **once instead of rerunning schema.sql**. Run the entire file as `postgres` in the SQL Editor.

The upgrade copies each existing student's intake and group into `student_intakes`, verifies the copy, updates group validation and timetable access rules, and only then removes `students.intake_id` and `students.group_number`. Student UUIDs, linked accounts, meetings, and change history are preserved. It pauses relevant writes during the change. An unexpected dependency on the old columns causes a rollback rather than being deleted automatically.

For a new database, use only `schema.sql`; it already includes this change. These are alternative setup paths. Neither script has been applied to a hosted project by this workspace.

No user accounts, passwords, or sample records are inserted. Create login accounts through **Authentication > Users**, then link their UUIDs through `auth_user_id`. Student/lecturer records can be imported before their accounts exist. Create the first admin record through the SQL Editor using the intended account's UUID; app users cannot promote themselves.

## Students with multiple intakes

`students` stores identity only. `student_intakes(student_id, intake_id, group_number)` stores memberships. Its composite primary key prevents a student joining the same intake twice, while allowing a different group in each intake. Memberships can be added or removed without duplicating or deleting the student's identity.

After loading the student seed, this example gives `TP000001` a second intake membership:

```sql
insert into public.student_intakes (student_id, intake_id, group_number)
select s.id, i.id, 2
from public.students s
cross join public.intakes i
where s.student_code = 'TP000001' and i.intake_code = 'APD2F2506CS'
on conflict (student_id, intake_id) do update
set group_number = excluded.group_number;
```

The student can then read classes and history for both matching intake/group combinations through the existing RLS policies. Membership rows are visible only to the owning student and admins. This model assumes a member attends every course assigned to that intake/group; selected-subject attendance would need course-level enrolments later.

To inspect memberships in the SQL Editor:

```sql
select s.student_code, s.full_name, i.intake_code, m.group_number
from public.students s
join public.student_intakes m on m.student_id = s.id
join public.intakes i on i.id = m.intake_id
order by s.student_code, i.intake_code;
```

## Sample classrooms

After creating the schema, run [seed_rooms.sql](seed_rooms.sql) in the SQL Editor. It creates 60 classrooms in Block B: levels 04 through 09, rooms 01 through 10 on each level. Each room has 50 seats except room 05 on each level, which has 100. Room 10 on each level is inactive, giving 54 active rooms and 6 inactive rooms.

It also creates 10 labs in Spine, named `LAB-04-01` through `LAB-04-10`. Every lab has 50 seats and type `lab`; only `LAB-04-10` is inactive. Spine also has `Auditorium 2`, an active auditorium with 500 seats. The complete room seed contains 71 rooms: 64 active and 7 inactive.

The script can be rerun: matching names have their sample values refreshed while retaining their existing UUIDs. Its final query summarizes each level so you can check the result.

## Sample lecturers

Run [seed_lecturers.sql](seed_lecturers.sql) in the SQL Editor after creating the schema. It inserts 20 fictional lecturers with distinct names and codes `LEC001` through `LEC020`. Login accounts can be linked later through `auth_user_id`.

Rerunning updates the sample names while preserving existing lecturer UUIDs and linked accounts. The final query lists all 20 records for inspection.

## Sample students and intakes

Run [seed_students.sql](seed_students.sql) after creating or upgrading the schema. It creates or updates these nine intakes, inserts 1,000 fictional student identities with codes `TP000001` through `TP001000` and distinct generated names, and adds 1,000 initial memberships:

| Intake code | Students | Groups | Students per group |
| --- | ---: | ---: | --- |
| APD1F2407CS(CYB) | 100 | 3 | 34, 33, 33 |
| APD1F2407CS | 200 | 6 | 34, 34, 33, 33, 33, 33 |
| APD1F2407CS(SE) | 40 | 1 | 40 |
| APD2F2506CS(CYB) | 100 | 3 | 34, 33, 33 |
| APD2F2506CS | 200 | 6 | 34, 34, 33, 33, 33, 33 |
| APD2F2506CS(SE) | 40 | 1 | 40 |
| APD3F2609CS(CYB) | 80 | 2 | 40, 40 |
| APD3F2609CS | 200 | 6 | 34, 34, 33, 33, 33, 33 |
| APD3F2609CS(SE) | 40 | 1 | 40 |

No login accounts are created. Rerunning refreshes the sample students' names and the planned initial memberships' group numbers while preserving their existing UUIDs, linked accounts, and any additional intake memberships. Other records are not deleted. Existing codes in the `TP000001` through `TP001000` range are treated as this sample dataset.

The summary query shows only the 1,000 planned initial memberships and their group sizes, excluding any extra memberships added later. An existing higher group number that would become invalid prevents the intake update and rolls back the script; resolve that membership deliberately before retrying.

## What is included

- The latest student identity/membership, intake/group, course type/duration, class, meeting, and audit tables.
- Required fields, foreign keys, uniqueness, positive-duration checks, and indexes.
- Group-range validation on student memberships and class sections, protection against reducing an intake's maximum below an existing group, and validation when an offering changes intake.
- Duration locking after sessions exist, including cancelled sessions, and protection against changing the course linked to an existing session through its offering/section.
- A transaction-level integrity lock for configuration changes. These writes require the usual **READ COMMITTED** isolation level; this deliberately simple mechanism suits a small hackathon dataset.
- A view that calculates class end times without storing them on sessions.
- Row Level Security: signed-in users can read catalog data; students and lecturers can read their own identity records and relevant schedules. Admin accounts can read all application records. Anonymous clients have no table access.

## Scheduling work to add next

The schema does **not yet reject overlapping bookings or unsuitable/undersized rooms**. It also does not automatically insert change-history rows. The next step is a trusted scheduling operation that checks room, lecturer, and student availability across **both** session tables and **all** student intake memberships, handles simultaneous requests, and saves the booking and history together. Derive class rosters from matching `student_intakes.intake_id` and `group_number` rather than fields on `students`.

For that reason, this initial script grants app users **read access only**, including users represented in `admins`. Use the SQL Editor for initial data entry. Add narrowly scoped, authorized scheduling functions and admin operations before enabling app writes. A trusted server using `service_role` bypasses RLS and must perform its own authorization; never put that key in the browser.

The SQL Editor runs with elevated privileges. Verify app permissions with real signed-in test accounts, not only dashboard queries. Unlinked records are visible to admins, but do not appear as someone's personal timetable until linked.

Course code and type are unique together: `CS101 / lecture` and `CS101 / lab` can have different durations. The course-offering pair is unique for each intake, and each offering has at most one section for a given group. Meetings retain an explicit end time.

Once this setup is adopted, keep later schema changes in separate migration files rather than rerunning or editing the initial script on an existing database.

## Local validation

The scripts passed 89 checks against PostgreSQL through PGlite with a minimal mocked Supabase Auth schema: 50 schema/integrity/access checks and 39 seed/membership/upgrade checks. Coverage includes all thirteen tables, group limits, derived class end times, duration locking, role-based reads across multiple intake memberships, membership removal, preserved account links, idempotent sample scripts, and a data-preserving upgrade from the previous schema. Unexpected old-column dependencies are tested to abort the upgrade without losing data. This is not a live Supabase deployment or a simultaneous-request stress test.

To rerun from the project folder in PowerShell, with Node.js installed:

```powershell
npm install --prefix .sql-tools --no-save --package-lock=false @electric-sql/pglite
$env:NODE_PATH = Join-Path (Get-Location).Path '.sql-tools/node_modules'
node supabase/tests/schema.test.cjs
node supabase/tests/memberships.test.cjs
```

`tests/fixtures/legacy_schema.sql` is an archived test fixture used only to validate the upgrade. It is not a setup script for your project.

References: [Supabase RLS](https://supabase.com/docs/guides/database/postgres/row-level-security), [database functions](https://supabase.com/docs/guides/database/functions), and [PostgreSQL triggers](https://www.postgresql.org/docs/current/plpgsql-trigger.html).
