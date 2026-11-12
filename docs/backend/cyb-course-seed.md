# CS(CYB) course seed, years 1 to 3

Date: 12 November 2026. Script: [supabase/seed_courses_cyb.sql](../../supabase/seed_courses_cyb.sql). Test: [supabase/tests/courses-cyb.test.cjs](../../supabase/tests/courses-cyb.test.cjs). Back to the [backend record](agents.md).

## Hosted database state — 13 November 2026

The user ran the scripts on hosted Supabase: the course seed, the 9-module teaching plans and the student removal. The user then renamed the intakes to 2611 codes and removed the other intakes. Read-only queries on 13 November 2026 found the following:

| Intake now | Was | Students (group 1 / 2) | Offerings | Teaching plans |
| --- | --- | --- | ---: | ---: |
| `APD1F2611CS(CYB)` | `APD1F2407CS(CYB)` (Year 1) | 80 (40 / 40) | 30 | 12 |
| `APD2F2611CS(CYB)` | `APD2F2506CS(CYB)` (Year 2) | 80 (40 / 40) | 28 | 12 |
| `APD3F2611CS(CYB)` | `APD3F2609CS(CYB)` (Year 3) | 80 (40 / 40) | 24 | 12 |
| `APU1F2611CS(SE)` | unchanged | 40 (40 / –) | 6 | 6 |

- **Intakes:** these four only. The other 14 sample intakes are gone, including the earlier `APD1F2611CS(CYB)`, `APD1F2611CS(SE)` and other 2611 intakes. The old-to-new mapping follows from the offering counts and course codes. The same 80 students are still in all three CYB intakes.
- **Students:** 121 students and 280 memberships. One student has no intake. One student record is linked to a login account.
- **Courses:**
  - 85 course rows, 88 offerings and 170 sections.
  - One course row has no offering: `ur mom` (lecture), which looks like test data. It is not from these scripts.
- **Teaching plans:**
  - 42 plans and 588 lessons, all starting 16 Nov 2026 for 14 weeks, one lesson a week.
  - 36 plans are the CS(CYB) sample (`CS101-IDB/IN/PYP`, `CS201-ENTINV/OODJ/SDM`, `CS301-INV/ALG/VAPT`).
  - 6 belong to `APU1F2611CS(SE)`; those were not created by these scripts.
- **Class sessions:** 8, all for `APU1F2611CS(SE)`. The CYB intakes have no saved classes yet.

**The scripts still use the old intake codes.** At the user's request, only the documentation was updated. Running a script now behaves like this:

| Script | Effect if run now |
| --- | --- |
| `seed_courses_cyb.sql` | **Do not run.** It would create three new empty intakes with the old codes and give them a second copy of the offerings. |
| `seed_students.sql` | **Do not run.** It would bring back the 18 old intakes and all 1,000 sample students. |
| `seed_teaching_plans_cyb.sql` | Stops ("Expected 18 offerings … found 0"); changes nothing. |
| `remove_teaching_plans_cyb.sql` | Finds no plans under the old codes and does nothing. The 36 plans stay. |
| `revert_courses_cyb.sql` | Finds no offerings under the old codes and deletes nothing, because every CS(CYB) course is still used by the renamed intakes. |
| `remove_students_except_cyb_se.sql` | Stops ("Only 1 of the 4 kept intakes exist"); changes nothing. |

To use the remove or revert scripts again, replace the three old CYB codes with the 2611 codes first.

## Requirement

The user asked for course and intake data for the CS(CYB) cohort, covering the same modules their own intake takes. Year 1 and Year 2 modules come from the user's interim transcripts. Year 3 modules come from the `APD3F2609CS(CYB)` programme schedule. Internship is excluded. No student, grade or attendance data from the transcripts is stored in the seed or in this note.

## What it creates

| Intake | Year | Modules | Course components | Sections (2 groups) |
| --- | --- | ---: | ---: | ---: |
| `APD1F2407CS(CYB)` | 1 (both semesters) | 15 | 30 | 60 |
| `APD2F2506CS(CYB)` | 2 (both semesters, no Internship) | 14 | 28 | 56 |
| `APD3F2609CS(CYB)` | 3 (both semesters) | 12 | 24 | 48 |

- The intakes already exist from `seed_students.sql`, each with 2 groups. The seed creates a missing intake with `max_group = 2` and adds sections for groups 1 to `max_group`.
- Every component lasts 120 minutes, the same as the existing `seed_courses.sql`.
- Both components of a module share one lecturer. Lecturers `LEC004`–`LEC020` are assigned in turn. `LEC001`–`LEC003` are left to `APU1F2611CS(SE)`. Each Year 3 semester-1 module has its own lecturer.
- No teaching plans or class sessions are created.
- It works with or without `class_sections.required_room_type`. When the old column still exists, labs get `lab` and other components get `classroom`, the same as the old seed.
- It is atomic and can be rerun. A rerun updates the names and durations of its own courses and the lecturers of its offerings, and keeps all UUIDs.

## Course codes

At the user's request (12 November 2026), every code is `CS101-<module>` for Year 1, `CS201-<module>` for Year 2 and `CS301-<module>` for Year 3. The module part is the transcript abbreviation for Years 1 and 2 (for example `CS101-PYP` and `CS201-OODJ`) and a short abbreviation for Year 3 (for example `CS301-VAPT`).

**IN and PYP use the original Supabase courses** (user decision, 12 November 2026). The seed does not create `CS101-IN` or `CS101-PYP`. It links `APD1F2407CS(CYB)` to the existing lecture and lab rows created by `seed_courses.sql` and never changes them, so they keep "Introduction to Programming", 120 minutes and their UUIDs. `seed_courses.sql` must therefore run first; otherwise this seed stops with "Course CS101-IN (lecture) is missing" and changes nothing. Year 1 gets its own offerings (`LEC014` for IN, `LEC015` for PYP) and group sections. The `APU1F2611CS(SE)` offerings (`LEC001`, `LEC002`) stay as they are. The seed creates 78 course rows, and the other 4 are reused.

## Reverting

[supabase/revert_courses_cyb.sql](../../supabase/revert_courses_cyb.sql) (user request, 12 November 2026) deletes what the seed adds. It removes the cohort's class sections, its 82 intake offerings (including the Year 1 links to `CS101-IN`/`CS101-PYP`) and its 78 course rows. Run it as a whole in the SQL Editor; its final query should show `0, 0, 4`.

- **Kept:**
  - `CS101-IN`/`CS101-PYP` and everything else from `seed_courses.sql`.
  - The three intakes and their student memberships. `seed_students.sql` owns these, so an intake that this seed created because it was missing also stays.
  - Any course row that another intake's offering still uses.
- **Stops and deletes nothing** if a class session or teaching plan already uses one of the cohort's sections. Saved timetables and plans have audit and identity rules, so the revert does not remove them silently.
- It is atomic and can be rerun.

## Assumptions to confirm

- **Year 3 module abbreviations are made up**, because the programme schedule lists module names only.
- **Year 3 teaching types follow the schedule:** L/T becomes lecture + tutorial, L/LAB becomes lecture + lab, and T/LAB (IoT) becomes tutorial + lab.
- **Year 1 and 2 teaching types are not on the transcripts.** Hands-on programming and networking modules are lecture + lab: PYP, IN, IOOP, OODJ, SNA, CTF, SRE, WAPP and DSTR. All other modules, including MPU modules and Co-Curricular 2, are lecture + tutorial.
- **Both Year 3 electives are included:** Cloud Infrastructure and Services, and Internet of Things. The schema assumes that every member of an intake/group attends every course of that intake, so both electives count for all students.
- **Semesters are not stored.** The schema has no semester field. If a whole intake is scheduled without teaching plans, the modules from both of its semesters are treated as one week's demand. Teaching plans (first Monday, number of weeks) are what separate the semesters.

## Teaching plans

Scripts (first version 12 November 2026, reduced 13 November 2026 at the user's request):

- [supabase/seed_teaching_plans_cyb.sql](../../supabase/seed_teaching_plans_cyb.sql) adds the plans.
- [supabase/remove_teaching_plans_cyb.sql](../../supabase/remove_teaching_plans_cyb.sql) removes them.
- Test: [supabase/tests/teaching-plans-cyb.test.cjs](../../supabase/tests/teaching-plans-cyb.test.cjs).

**User decisions:**
- **A small set that can be scheduled** (13 November 2026, "the courses are too much for sample data"). Three Semester 1 modules per intake get plans:

  | Intake | Modules | Lecturers |
  | --- | --- | --- |
  | `APD3F2609CS(CYB)` | `CS301-INV` (L/T), `CS301-ALG` (L/T), `CS301-VAPT` (L/LAB) | `LEC004`–`LEC006` |
  | `APD2F2506CS(CYB)` | `CS201-ENTINV` (L/T), `CS201-OODJ` (L/LAB), `CS201-SDM` (L/T) | `LEC016`–`LEC018` |
  | `APD1F2407CS(CYB)` | `CS101-IDB` (L/T), `CS101-IN` (L/LAB), `CS101-PYP` (L/LAB) | `LEC013`–`LEC015` |

  These are the first three listed for each year. The nine lecturers are all different. The set includes the reused `CS101-IN`/`CS101-PYP`. The other 32 modules keep their courses and sections, but get no plan.
- All three intakes in the **same weeks**: **14 consecutive weeks** (breaks are not skipped), **1 lesson a week** per lecture, tutorial or lab of each group.
- The start Monday was not specified. The script uses **Mon 16 Nov 2026**, so the last lesson week starts 15 Feb 2027. Change `first_monday` at the top of the script to use another Monday.
- Superseded: the 12 November version planned all 41 modules (164 plans, 2,296 lessons). It could not be scheduled, because the same 80 students needed 164 h a week.

**How the numbers come about:** 9 modules × 2 teaching parts = 18 offerings. × 2 groups = **36 sections**, one plan each. × 14 weeks = **504 lessons** (12 plans and 168 lessons per intake). The plans are 18 lecture, 10 tutorial and 8 lab.

**What the plan script does:**
- Adds the 36 plans. The database creates the lessons; no times, rooms or class sessions are assigned. Generate Preview on `/admin/schedule` places them.
- Stops in these cases:
  - the migration `202611100001_teaching_requirements.sql` or the CS(CYB) courses are missing;
  - a planned section already has a different plan;
  - **any other CS(CYB) module still has a plan**, for example from the 12 November version. That would bring the overload back, so run the removal script first.
- Adds nothing when rerun.

**Schedulable, checked with the real solver.** `seed_students.sql` puts the same 80 students in all three intakes, in the same group, so each student has 18 two-hour classes (36 h) a week. A synthetic week mirrored the plans, the student groups and the `seed_rooms.sql` rooms, with no other bookings. Running the project's solver with its configured settings (120 s limit, preferences on):
- **OPTIMAL: all 36 lessons placed**, in 91 s, of which 78 s improved the timetable.
- No idle time between classes for students or lecturers.
- 7, 8, 7, 8 and 6 classes Monday to Friday, across both groups.
- 11 classes in labs and 25 in classrooms, with no auditorium.

Bookings already in the hosted database (other intakes' classes or meetings) were not included. They can only add room clashes, because these students and lecturers have no other classes. The scratch check script was not added to the repository.

**The removal script:**
- Deletes every plan and lesson on all 41 CS(CYB) modules: the 36 from the current script, plus any left from the 12 November version. It keeps courses, offerings, sections, intakes and other intakes' plans, including `APU1F2611CS(SE)`'s own `CS101-IN`/`CS101-PYP` sections.
- **Deliberate exception:** the database normally refuses to delete a lesson ("cancel instead of deleting its identity"). The script switches off only the `validate_teaching_occurrence` trigger, and only inside its own transaction. It switches it back on before the transaction ends, so other sessions never see it off.
- Stops, deleting nothing, if any class session is linked to one of these lessons, because a saved timetable keeps its lesson history.
- Its final query shows `0, 0, O`; `O` means the protection is back on.

**Undo order:** run `remove_teaching_plans_cyb.sql` first, then `revert_courses_cyb.sql`. The course revert refuses while plans exist.

**Verification:** 33 checks passed (PGlite, mocked Supabase Auth). They ran on the schema after the hosted migrations: teaching requirements, room-column removal, `rescheduled` status and save audit. Covered:

- missing migration or missing courses;
- per intake: 3 modules, 12 plans, 168 lessons;
- exactly the nine chosen modules, with nine lecturers and 18/10/8 lecture/tutorial/lab plans;
- 16 Nov 2026 start, 14 weeks, 1 a week, last week 15 Feb 2027;
- 36 lessons waiting in the first week, with no class sessions created;
- rerun adds nothing;
- a different plan on a planned section, or a plan on another CS(CYB) module, stops the script;
- removal blocked by a linked class session;
- removal keeps another intake's plan, also deletes plans on unplanned CS(CYB) modules, and deleting a lesson is still refused afterwards;
- rerunning the removal;
- the full undo order.

The `courses-cyb` suite still passes (75). Not run on hosted Supabase.

## Removing the other sample students

[supabase/remove_students_except_cyb_se.sql](../../supabase/remove_students_except_cyb_se.sql), added 13 November 2026 at the user's request. Test: [supabase/tests/remove-students.test.cjs](../../supabase/tests/remove-students.test.cjs).

- **Kept intakes:** the three CS(CYB) intakes and `APU1F2611CS(SE)`. The user first wrote `APD1F2611CS(SE)`, then confirmed `APU1F2611CS(SE)`, the SE intake that has the `seed_courses.sql` classes.
- **Removes** every student who belongs only to other intakes, with their memberships and meeting attendance. On the sample data that is 880 of the 1,000 students and 1,200 of the 1,480 memberships. It leaves 120 students: 80 in each CS(CYB) intake (40 per group) and 40 in `APU1F2611CS(SE)`.
- **Other cases:**
  - A student who is also in a kept intake is kept, but loses memberships elsewhere, so the other intakes end up empty.
  - Students with no membership are not touched.
  - Intakes, courses, sessions, meetings, plans and Auth accounts are kept.
- **Stops, deleting nothing:**
  - if a kept intake code does not exist (a typo would otherwise delete that intake's students);
  - if a student to be removed is linked to a login account, unless `remove_linked_accounts` is set to `true` in the script.
- **Undo:** rerun `seed_students.sql`. Removed students come back with new UUIDs and no login link.
- **Verification:** 20 checks passed (PGlite, mocked Supabase Auth) on the real 1,000-student seed. They cover:
  - the counts above, with unchanged kept memberships and group sizes;
  - the mixed-membership and no-membership cases;
  - meeting attendance;
  - the login-link guard and the typo guard;
  - rerunning the script, and restoring with `seed_students.sql`.

  Not run on hosted Supabase.

## Year 3 calendar teaching weeks (reference, not used by the plan script)

These are the teaching weeks from the programme schedule, with the break weeks left out. A plan covers consecutive weeks, so each block would be a separate plan for each section:

- Semester 1: 14 Sep–8 Nov 2026 (8 weeks), 16 Nov–20 Dec 2026 (5 weeks), 4–10 Jan 2027 (1 week).
- Semester 2: 15 Feb–7 Mar 2027 (3 weeks), 15 Mar–25 Apr 2027 (6 weeks), 3 May–6 Jun 2027 (5 weeks).

## Verification

`node supabase/tests/courses-cyb.test.cjs`: **75 checks passed**. These include 22 revert checks: blocked by a class session, and by a teaching plan, with nothing deleted; a clean revert; `seed_courses.sql` rows, the `APU1F2611CS(SE)` offerings and the intakes kept; rerunning the revert; and keeping a course another intake uses. 53 seed checks passed before the revert was added (PGlite, mocked Supabase Auth). Both scenarios run `seed_courses.sql` first: one on the legacy `schema.sql`, the other followed by the teaching-requirement and room-column-removal migrations. The checks cover:

- rollback when a lecturer is missing, and when `CS101-IN`/`CS101-PYP` are missing;
- CS101/CS201/CS301 codes by year;
- 78 new course rows; the existing `CS101-IN`/`CS101-PYP` rows unchanged and linked to Year 1; the `APU1F2611CS(SE)` offerings unchanged;
- counts per intake;
- 120-minute components;
- Internship excluded;
- one lecturer per module;
- Year 3 component types;
- legacy room types;
- no sessions created;
- unchanged IDs after a rerun.

The existing `courses.test.cjs` still passes (20 checks). The seed has not been run on hosted Supabase.
