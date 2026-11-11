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

## Add age to an existing database

For an existing database, run [migrations/202611080002_student_age.sql](migrations/202611080002_student_age.sql) before the updated student seed. It adds integer `students.age` without deleting records. Existing unknown ages remain NULL; negative ages are rejected. A new database created with the latest `schema.sql` already has this column. If you still have the single-intake schema, apply the membership upgrade first, then the age migration.

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

The student seed reserves `TP000001` through `TP001000`: rerunning it replaces all memberships for those sample codes with the current cohort plan, including any manually added memberships. Use student codes outside that range for records whose memberships should be independent of the sample seed.

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

## Courses for APU1F2611CS(SE)

Run [seed_courses.sql](seed_courses.sql) as `postgres` in the SQL Editor after `schema.sql` and `seed_lecturers.sql`. It creates the intake with one group if missing, then creates these course components, intake offerings, and Group 1 class sections:

| Course code | Subject | Components | Lecturer | Duration of each component |
| --- | --- | --- | --- | ---: |
| CS101-PYP | Introduction to Programming | Lecture + lab | LEC001 - Ahmad Hakim | 120 minutes |
| CS101-IN | Introduction to Networking | Lecture + lab | LEC002 - Siti Aisyah | 120 minutes |
| CS101-ISE | Introduction to Software Engineering | Lecture + tutorial | LEC003 - Muhammad Farhan | 120 minutes |

Both components of each subject use the same lecturer. Lectures and the tutorial require a classroom; labs require a lab. There are six course rows because teaching type is part of the course identity, with six intake offerings and six Group 1 sections. Dated class sessions are scheduled later.

The script is atomic, uses no temporary tables, and can be rerun while preserving existing course/offering/section UUIDs. Rerunning refreshes the listed course names/durations and the target intake's lecturer and room-type assignments. A missing lecturer or a conflicting duration protected by existing sessions causes rollback. The final query lists all six components for inspection.

## Sample students and intakes

Run [seed_students.sql](seed_students.sql) after creating or upgrading the schema (including the age migration). It creates or updates 18 intake codes and generates **1,000 unique student identities with 1,480 memberships**, arranged as the twelve cohorts below. Codes remain `TP000001` through `TP001000`, with distinct generated names and integer ages 18 through 25 (125 students per age).

Paste the entire updated file into a new SQL Editor query and run it with no partial selection. The seed is a single atomic `DO` block with no temporary tables; its verification query is self-contained and can also run separately. If the block fails, its inserts and updates are rolled back together. There is no need to create or clear a planning table.

| Intake code(s) for the same cohort | Unique students | Groups per intake | Students per group in each intake |
| --- | ---: | ---: | --- |
| APU1F2611CS(CYB) | 100 | 3 | 34, 33, 33 |
| APU1F2611CS | 100 | 3 | 34, 33, 33 |
| APU1F2611CS(DF) | 100 | 3 | 34, 33, 33 |
| APU1F2611CS(SE) | 40 | 1 | 40 |
| APD1F2611CS(CYB) | 100 | 3 | 34, 33, 33 |
| APD1F2611CS | 100 | 3 | 34, 33, 33 |
| APD1F2611CS(DF) | 100 | 3 | 34, 33, 33 |
| APD1F2611CS(SE) | 40 | 1 | 40 |
| APD1F2407CS(CYB), APD2F2506CS(CYB), APD3F2609CS(CYB) | 80 | 2 | 40, 40 |
| APD1F2407CS, APD2F2506CS, APD3F2609CS | 80 | 2 | 40, 40 |
| APD1F2507CS(CYB), APD2F2606CS(CYB) | 80 | 2 | 40, 40 |
| APD1F2507CS, APD2F2606CS | 80 | 2 | 40, 40 |

Each of the last four rows represents the same 80 students belonging to every intake listed in that row. These are not separate sets of 80 for each code. The final cohort uses `APD2F2606CS` without `(CYB)`, as confirmed. The first eight cohorts account for 680 unique students; the final four account for 320. Their membership counts total 680 + 240 + 240 + 160 + 160 = 1,480.

No login accounts are created. Rerunning refreshes sample names/ages and **replaces all intake memberships for the reserved 1,000 sample student codes**. Student UUIDs, linked accounts, meeting attendance, and other students' memberships are preserved. Obsolete memberships from the previous seed are removed before intake group limits are reduced. Older intake records themselves are retained, along with shared course/schedule records.

The independent summary query shows actual sample memberships by intake and group: 18 rows, totaling 1,480 memberships. It counts memberships rather than unique student identities. Existing non-sample memberships or class sections using groups above a new maximum cause the entire seed to roll back; adjust those deliberately before retrying.

## Reset student data

Run the entire [reset_students.sql](reset_students.sql) file as `postgres` in the SQL Editor to delete **all** student identities, intake memberships, and student meeting-attendance records. It keeps Supabase Auth accounts, lecturers, admins, intakes, courses, rooms, class sessions, meeting sessions, and change history. Login links are removed with the student identities. The deletes run in one transaction and do not cascade into other tables.

You can then rerun `seed_students.sql` to recreate the sample students and their 1,480 planned memberships. Recreated students receive new UUIDs and have no linked login accounts until you link them again. A reset is not required just to switch from the previous intake plan: the new seed replaces sample memberships itself while preserving existing student IDs.

## What is included

- The latest student identity/membership, intake/group, course type/duration, class, meeting, and audit tables.
- Required fields, foreign keys, uniqueness, positive-duration checks, and indexes.
- Group-range validation on student memberships and class sections, protection against reducing an intake's maximum below an existing group, and validation when an offering changes intake.
- Duration locking after sessions exist, including cancelled sessions, and protection against changing the course linked to an existing session through its offering/section.
- A transaction-level integrity lock for configuration changes. These writes require the usual **READ COMMITTED** isolation level; this deliberately simple mechanism suits a small hackathon dataset.
- A view that calculates class end times without storing them on sessions.
- Row Level Security: signed-in users can read catalog data; students and lecturers can read their own identity records and relevant schedules. Admin accounts can read all application records. Anonymous clients have no table access.

## Scheduling work to add next

The historical [migrations/202611100003_scheduling_snapshot.sql](migrations/202611100003_scheduling_snapshot.sql) adds an optional server-side snapshot RPC. Current schedule generation reads existing tables and views directly from the backend and does not require this migration. See [loader setup, consistency limits, and validation](../docs/backend/scheduling-data-loader.md).

Weekly demand is available through [migrations/202611100001_teaching_requirements.sql](migrations/202611100001_teaching_requirements.sql). Apply it **once after the base schema** (or the existing membership/age upgrades); do not rerun the initial schema. It works whether the optional `202611100002_remove_required_room_type.sql` patch has been applied or not. It adds `teaching_plans`, `teaching_occurrences`, an optional occurrence link on `class_sessions`, and the `teaching_occurrence_details` view without using the legacy room field. Existing data is retained. See [setup and usage](../docs/backend/weekly-teaching-plans.md).

Create a plan for each lecture/lab section with its first Monday, number of weeks, and occurrences per week. Plan insertion creates required lessons without assigning times or rooms. The SQL Editor and trusted server role can maintain these records; application users retain read-only access. No hosted migration or production teaching-plan data has been applied by this task.

The schema does **not yet reject overlapping bookings or unsuitable/undersized rooms**. It also does not automatically insert change-history rows. The next step is a trusted scheduling operation that checks room, lecturer, and student availability across **both** session tables and **all** student intake memberships, handles simultaneous requests, and saves the booking and history together. Derive class rosters from matching `student_intakes.intake_id` and `group_number` rather than fields on `students`.

For that reason, this initial script grants app users **read access only**, including users represented in `admins`. Use the SQL Editor for initial data entry. Add narrowly scoped, authorized scheduling functions and admin operations before enabling app writes. A trusted server using `service_role` bypasses RLS and must perform its own authorization; never put that key in the browser.

The SQL Editor runs with elevated privileges. Verify app permissions with real signed-in test accounts, not only dashboard queries. Unlinked records are visible to admins, but do not appear as someone's personal timetable until linked.

Course code and type are unique together: `CS101 / lecture` and `CS101 / lab` can have different durations. The course-offering pair is unique for each intake, and each offering has at most one section for a given group. Meetings retain an explicit end time.

Once this setup is adopted, keep later schema changes in separate migration files rather than rerunning or editing the initial script on an existing database.

## Local validation

The scripts passed 130 checks against PostgreSQL through PGlite with a minimal mocked Supabase Auth schema: 52 schema/integrity/access checks and 78 seed/membership/upgrade checks. Coverage includes all thirteen tables, group limits, integer age validation, sample ages 18 through 25, derived class end times, role-based access, and data-preserving upgrades. Seed checks cover the exact group sizes for 18 intakes, shared student identities across linked intakes, 1,000 unique students with 1,480 memberships, replacement of outdated sample memberships, preservation of other students and login links, and conversion of the previous nine-intake dataset. The seed and verification query are tested separately without temporary tables. A late failure restores removed memberships and earlier records. This is not a live Supabase deployment or a simultaneous-request stress test.

To rerun from the project folder in PowerShell, with Node.js installed:

```powershell
npm install --prefix .sql-tools --no-save --package-lock=false @electric-sql/pglite
$env:NODE_PATH = Join-Path (Get-Location).Path '.sql-tools/node_modules'
node supabase/tests/schema.test.cjs
node supabase/tests/memberships.test.cjs
node supabase/tests/courses.test.cjs
node supabase/tests/teaching-requirements.test.cjs
node supabase/tests/room-type-removal.test.cjs
node supabase/tests/scheduling-snapshot.test.cjs
```

The course seed additionally passed 20 checks against the current schema, covering the six teaching components, 120-minute durations, paired lecturer assignments, room types, rollback on missing lecturers, preservation of IDs on rerun, and preservation of scheduled sessions.

The teaching-requirement migration passed 51 additional checks covering weekly expansion, stable identities, repeated materialization, period boundaries, cancellation, make-up demand, booking linkage, timezone week mapping, preserved legacy data, protected teaching metadata, and role-based access. All four suites passed together during step 2 verification (201 database checks total). This remains local PostgreSQL verification with mocked Auth, not a hosted deployment or concurrent-transaction stress test.

Step 4 verification also passed 25 room-removal checks and 32 snapshot checks, bringing all six suites to 258 passing database checks. Snapshot coverage includes deduplicated cross-intake rosters, complete weekly input, derived end times, boundary overlaps, cancelled-booking exclusion, read-only access, role grants, and compatibility with the room-removal patch. Synthetic fixtures are local test data and are not inserted into the hosted dataset.

`tests/fixtures/legacy_schema.sql` is an archived test fixture used only to validate the upgrade. It is not a setup script for your project.

References: [Supabase RLS](https://supabase.com/docs/guides/database/postgres/row-level-security), [database functions](https://supabase.com/docs/guides/database/functions), and [PostgreSQL triggers](https://www.postgresql.org/docs/current/plpgsql-trigger.html).
