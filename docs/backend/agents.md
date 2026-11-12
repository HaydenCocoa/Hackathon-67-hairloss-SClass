# Backend record

Last updated: 13 November 2026 (Asia/Kuala_Lumpur).

## Documentation convention

This is the main record for backend requirements, decisions, implemented changes, planned work, verification, and unresolved questions. Keep it updated whenever backend work changes. Put detailed notes in separate Markdown files in this directory and link them here. Clearly distinguish implemented behavior from proposals and plans.

The user requested this convention on 10 November 2026. Repository-level `AGENTS.md` records it for future work. The separate checklist `task_hayden.md` was removed on 12 November 2026 at the user's request because the work is nearly done. Its open items are now in [Remaining work](#remaining-work) below, which is the single list of what is left.

## Project direction

- Build the scheduling backend before the remaining frontend, notification, and AI features.
- Target one teaching week initially, with existing student groups, fixed lecturers, and one room per class.
- Prevent conflicts using actual student identities across all their intake memberships.
- Respect both class and meeting bookings and preserve future reservations.
- Generate a valid timetable before optimizing student gaps, lecturer gaps, and room utilization.
- OR-Tools CP-SAT feasibility generation is implemented and verified locally in step 7. Simpler candidate search and ranking for one-class rescheduling remain planned.
- Separate generation previews from authorized, transactional booking commits.

Source: [Notes / Hackathon](https://app.notion.com/p/4117da63706d807095f2fbdab3321a17), last edited 9 November 2026. The lecturer use case includes cancelling or moving a class to a scheduled week or reserving a placement before a future week is generated.

## Accepted calendar decisions

- `Config/config.json` controls teaching weekdays and opening hours.
- Initial hours: Monday–Friday, 08:30–18:00, `Asia/Kuala_Lumpur`.
- A class may start at any whole minute (since 12 November 2026) if its full duration fits inside opening hours. No fixed start-time grid or travel buffer.
- Two bookings (classes or meetings) that share a room, lecturer or student must be at least `min_gap_minutes` (15) apart. Added 12 November 2026; the scope, including meetings, was confirmed the same day.
- Omitted weekdays are closed. Explicit closure dates override weekly hours; the initial closure list is empty.
- Timestamps must include timezone information. Calendar eligibility is separate from resource availability.

See [step 1: configurable teaching calendar](scheduling-calendar.md) for the configuration, rationale, code interface, behavior examples, affected files, and verification details.

## Current implementation

Status on 12 November 2026. The dated entries further down give the detail and test results.

- **Platform:**
  - Health and configuration checks, and frontend serving.
  - Login at `/login` with Supabase Auth and httpOnly session cookies; one role per account (admin > lecturer > student). See [login](login.md).
  - Role-based access on every API.
- **Scheduling engine (steps 1–8):**
  - Configurable teaching calendar.
  - Database-defined weekly teaching plans with stable occurrences.
  - Backend-owned data loader. Its direct PostgREST reads are not yet verified: 10 older loader/preview tests still fail.
  - Shared booking validator and candidate start ranges.
  - Joint CP-SAT generation that improves the timetable with the configured preferences (student waiting time, lecturer gaps, room fit). The 15-minute gap, whole-minute starts and the auditorium rule are compulsory. See [timetable quality](timetable-quality.md).
- **Preview and save (steps 9–10):** admin-only API, usable in production (Vercel) since 12 November 2026 ([details](vercel-deployment.md#scheduling-on-vercel-since-12-november-2026)); the test page stays local-development only.
  - The save rechecks the week and writes all classes in one insert, with an audit row per class ([timetable saving](timetable-saving.md), [save audit](save-audit.md)).
  - There is no lock shared with the other writers.
- **Rescheduling (step 11), partly built:**
  - `rescheduled` status ([details](rescheduled-status.md)).
  - The lecturer page's move endpoint: reviewed on 12 November, re-checked after the teammate's update, then fixed the same day. It now uses the engine's rules and `lecturer_reschedule_class` (one transaction under the lock), and errors are safe ([fix](lecturer-reschedule-review.md#fix-12-november-2026)). IDs are still not validated.
  - The admin page's Reschedule dialog and its availability/reschedule API ([admin rescheduling API](admin-reschedule-api.md)).
  - The admin page's reschedule database function, fixed on 12 November for the removed room column and the `rescheduled` status.
  - Cancellation and future reservations are not built.

The separate PostgREST reads are not one transaction snapshot, so any booking write must recheck before writing.

## Development roadmap and status

| Step | Requirement and completion target | Status |
| --- | --- | --- |
| 1 | Configurable teaching calendar and reusable full-interval eligibility check | Complete; verified |
| 2 | Database-backed weekly teaching requirements and stable occurrences, with cancellation and replacement tracking | Complete; confirmed by the user on 11 Nov. Original design verified locally; no automated results recorded for the 11 Nov room-field compatibility edit |
| 3 | Use existing database scheduling inputs; defer meeting and impossible-arrangement fixtures for the initial MVP | Complete based on user confirmation; no new runtime code |
| 4 | Backend loader reads existing scheduling data and builds a validated engine snapshot | Backend implementation updated to direct PostgREST reads on 11 Nov; verification pending |
| 5 | Explainable room, lecturer, student, and reservation conflict validation | Complete and verified locally; no new migration |
| 6 | Feasible start ranges and suitable rooms without preset teaching slots | Complete and verified locally; no new migration |
| 7 | CP-SAT generation satisfying all mandatory constraints and reporting accurate solver status | Complete and verified locally; no new migration |
| 8 | Configurable objectives for student gaps, lecturer gaps, and room utilization | Implemented and verified locally 12 Nov ([timetable quality](timetable-quality.md)), with the compulsory 15-minute gap, whole-minute starts and auditorium rule |
| 9 | Selected-intake/group preview API and test page including assignments, diagnostics, quality measurements, and scope-bound input revision | Complete and verified locally. Admin login; production (Vercel) use since 12 Nov, live deployment not checked. Test page local only |
| 10 | Authorized, transactional commits with revalidation, concurrency control, audit, and retry protection | Save implemented and verified locally on 11 Nov (recheck-then-single-insert). Admin login required since 12 Nov ([login](login.md)); save audit implemented 12 Nov ([save audit](save-audit.md)). Not run against hosted Supabase |
| 11 | Safe rescheduling, cancellation, and fixed future reservations | In progress. `rescheduled` status added 12 Nov ([details](rescheduled-status.md)). Lecturer move endpoint exists but misses compulsory rules ([review](lecturer-reschedule-review.md)). Admin reschedule function fixed 12 Nov. Cancellation and reservations not built. Hosted SQL runs pending |
| 12 | Verified requirements-to-generation-to-commit-to-retrieval workflow and acceptance scenarios | Planned |

## Verification and completion record

### 10 November 2026 — Step 1 and documentation convention

- User confirmed Monday–Friday, 08:30–18:00 and removed start-time slot and break requirements.
- Added the calendar configuration, validation, internal helper, app initialization, timezone dependency, and automated calendar/startup checks.
- Installed `tzdata` 2026.6 locally after an approved network retry.
- Updated the root development checklist to remove superseded slot/break rules from later steps.
- Added this record, detailed calendar documentation, README links, and repository documentation instructions.
- Focused calendar and startup checks: **29 passed**.
- Full backend suite (`.venv/Scripts/python.exe -m pytest backend/tests -q`): **43 passed, 1 skipped**, with one existing test-client deprecation warning. The skipped test requires the optional Postman simulation, which was not running.
- The restricted integration-test run stalled in Windows asyncio local socket creation. Stopped those runs and reran with approved local networking; the full suite passed in 10.29 seconds. Tests use a local stand-in, not the hosted Supabase project.
- `git diff --check` passed. Step 1 is complete; timetable generation itself remains planned.

## Remaining work

The single list of what is left (moved here from the removed `task_hayden.md` on 12 November 2026). The dated entries below give the background.

**Step 11: rescheduling, cancellation and reservations**
- Admin page: **done 12 November 2026.** A Reschedule dialog backed by the availability and reschedule endpoints, which use the engine's rules ([admin rescheduling API](admin-reschedule-api.md)).
- Lecturer move endpoint: **switched to `scheduling/reschedule.py` and `lecturer_reschedule_class` on 12 November 2026** ([fix](lecturer-reschedule-review.md#fix-12-november-2026)), fixing opening hours, room rules, locking, error text and the lost intake code/group size. Still open: validate IDs (finding 9). Apply migration `202611120004` on hosted Supabase. The review's original list was:
  - opening hours
  - the 15-minute gap
  - room type and the auditorium rule
  - lock and transaction
  - past classes
- Rank other times for one class. Free times are now listed per room and day (admin availability endpoint), but they are not ranked yet.
- Save a replacement and its history in one transaction, keeping the original if the replacement fails: done for admin moves (the database function); still open for the lecturer endpoint.
- Deliberate cancellation that frees the class's resources.
- Future reservations (lecturer, students, room) that later generation treats as fixed. Keep "published" separate from "occupies resources".
- Permission check on every cancel, reschedule and reservation.
- Admin reschedule database function: add opening hours and the 15-minute gap. The new admin endpoint checks them before calling it, but the older `PUT /api/admin/timetable/{id}` does not.

**Production check:** run one preview, one save and one admin move on the live Vercel site, and check the function's run time in Vercel's logs and that the project uses Fluid compute ([details](vercel-deployment.md#scheduling-on-vercel-since-12-november-2026)).

**Step 12: verify the whole workflow.** No item is started:
- The acceptance scenarios: cross-intake students, the only suitable lab, no big-enough room, a meeting clash, a reservation preserved, repeated generation, cancelled lessons, freed resources, two requests for one resource, a failed replacement, a stale preview, an unresolved search, a missing placement.
- Reading the timetable back after a save.
- Rechecking the output with the validator.
- Two saves at the same time.

**Step 10 leftover:** one lock or rule that every writer of bookings follows. The save, the admin function, the lecturer endpoint and the dashboard do not share one today.

**Step 4 / tests:**
- Verify the direct-read loader against real data.
- Update the 10 older loader/preview tests that still expect the removed RPC or the `required_room_type` field.

**Admin page (12 November 2026 changes)**
- Check the intake-student endpoints and the intake list's embedded counts against hosted Supabase ([entry](#admin-page-clean-up-intake-students-and-intake-charts--12-november-2026)).

**Admin page (13 November 2026 changes)**
- On hosted Supabase, add one test student and one test lecturer, log in with each temporary password, change it on `/change-password`, then delete both test logins ([admin-created logins](admin-accounts.md), [forced change](login.md#forced-password-change)). This checks that `SUPABASE_KEY` may use the Auth admin API, that the project's password rules accept code + 4 digits, and that the flag is cleared.
- Not built (would need a new request): deleting a lecturer's login together with the lecturer, and a voluntary "change password" link.

**Deferred by the user (12 November 2026, not a priority; scheduling stays as it is)**
- A "fewer days on campus" preference.
- Course-offering end dates.

**Hosted setup (project owner)**
- Run these migrations on Supabase. The user asked for an explanation first: see [migrations to apply](hosted-migrations.md).
  - `202611100002_remove_required_room_type`
  - `202611120001_class_session_rescheduled_status`
  - `202611120002_save_audit`
  - `202611120003_admin_reschedule_fixes`
  - `202611120004_lecturer_reschedule` (lecturer moves in one transaction; needed by the lecturer page since 12 November 2026)
  - and `202611110001_admin_timetable` if it is not applied yet

**Settled by the user on 12 November 2026 (no action)**
- Supabase accounts: the data is hackathon sample data, so no extra account work is planned.
- Vercel: the user reports that setup is complete. Vercel is used **for production only**; development stays local. Since 12 November 2026 (later the same day) the scheduling preview and save work there too; see [Vercel deployment](vercel-deployment.md#scheduling-on-vercel-since-12-november-2026).
- The old course seed, fresh setup (`schema.sql` still has `required_room_type`) and the ERD will not be updated for the removed room column.

**Known limits**
- `closed_dates` is empty; public holidays are not imported. Opening windows are same-day only.
- The scheduling input is several reads, not one database snapshot.

## Step 2 discussion — 10 November 2026

Historical discussion; superseded by the implementation record below after the user confirmed weekly recurrence over an identified period.

- The user requested discussion before implementation and asked how each week's occurrences are fetched from the database.
- The proposed aim is to identify database-backed teaching demand for the selected week, separately from the final time/room assignments. Requirements may repeat or differ between weeks; repeated weekly classes still have distinct occurrence identities.
- Schema review confirmed that courses, offerings, sections, and dated sessions exist, but explicit weekly teaching requirements and their linkage to bookings do not.
- A recurring database teaching plan with weekly exceptions is recommended for discussion; explicitly authoring every week's requirements is an alternative. The user has not selected either approach yet.
- Occurrence lifecycle, teaching-period/week mapping, and who maintains the plan remain design questions. No step 2 runtime code, migration, or hosted data changes have been made.
- See [weekly teaching requirements discussion](teaching-requirements.md) for the rationale, proposed flow, and completion target. Documentation-only checks apply to this change; no runtime tests were rerun.
- Documentation links and `git diff --check` passed. The current `.venv` could not launch its referenced base Python executable during an attempted link check; PowerShell was used for that check instead. Restore a working Python environment before future runtime verification.

## Offering end-date and room-policy review - 10 November 2026

- The user proposed an end date on each course offering, deferring automatic holiday/semester-break handling, and removing `class_sections.required_room_type` in favor of system-defined room selection.
- Both structural changes are reasonable with coordinated rules. Recommended date semantics are an inclusive last teaching date in the campus timezone, consistent with recurring teaching-plan bounds. Whether the cutoff also blocks make-up classes needs confirmation; the recommended initial policy is a hard boundary with explicit extensions.
- Removing the room requirement depends on a defined system compatibility mapping from course type to allowed room types. Real room classification, capacity, active status, and resource availability remain necessary. A proposed mapping is documented, not activated.
- Existing calendar rules remain Monday-Friday, 08:30-18:00, unrestricted start times that fit the full interval, and explicit configured closures. No automatic holiday/break calendar is introduced.
- Existing uncommitted step 2 migration/loader drafts still depend on `required_room_type` and define recurrence bounds independently. This review did not edit, execute, or validate those draft runtime files and does not mark step 2 complete.
- Added [detailed proposal assessment and implementation considerations](offering-end-dates-and-room-policy.md), and aligned the checklist with the unresolved decisions. No schema, configuration, seed, application behavior, or hosted data changed. Runtime tests were not rerun for this documentation-only work.

## Step 2 implementation — 10 November 2026

- User confirmed repeating lecture/lab teaching over a defined period and requested implementation. Added one plan per section, with first Monday, positive week count, occurrences per week, and timezone. No actual production teaching dates were invented.
- Added `202611100001_teaching_requirements.sql`: two tables, automatic transactional recurrence expansion, stable source identities, target weeks, idempotent expansion, occurrence/booked-session linkage, access policies, and `teaching_occurrence_details`.
- Lecture/lab metadata is resolved from existing sections, courses, and offerings. Plan definitions and linked teaching metadata are protected after expansion. See detailed notes for the deliberate limitation on later staffing/curriculum revisions.
- Cancellation stays cancelled across re-expansion. Explicit make-up demand reopens the same occurrence and selects a target week; dated booking moves synchronize target weeks without changing original identity.
- Existing sessions are retained and not automatically linked. Legacy bookings must be reconciled before new generation for their period.
- Added `TeachingPlanInput`, `TeachingOccurrence`, and `load_weekly_requirements` in `backend/app/scheduling/requirements.py`. The reader fetches all or only outstanding demand for one Monday-anchored target week, with pagination and explicit malformed/missing-view/timeout failures. It is internal; no unauthenticated write or generation endpoint was added.
- The offering-end-date proposal remains deferred. The original Step 2 migration retained `required_room_type`; this was superseded by the 11 November update below. No offering end date or automatic holiday/break handling is introduced.
- No hosted project was contacted or changed. Apply the additive migration once and enter actual section teaching periods to use it in Supabase.
- Documentation: [weekly teaching plans](weekly-teaching-plans.md), [original discussion](teaching-requirements.md), root README, database README, and `task_hayden.md`.
- Verification: focused reader/input suite **16 passed**; full backend suite **59 passed, 1 optional simulation test skipped**, with one existing test-client deprecation warning. Database checks: **51** new teaching-requirement checks, **52** schema/integrity/access, **78** membership/seed/upgrade, and **20** course-seed checks all passed (**201 total**). `git diff --check` and local documentation-link checks passed.
- Environment: the existing virtual environment's base interpreter remains missing. An ignored project-local CPython 3.12.10 runtime from Python.org was used with the existing packages for verification. No global Python configuration was changed. Local PGlite tooling was installed in ignored `.sql-tools/`.
- New HTTP behavior was tested against a synthetic local server because Postman CLI is unavailable. The existing CLI mock still covers only the rooms probe. These results do not establish live provider deployment or concurrent-transaction stress behavior.
- Verification: `git diff --check` passed and local links in the new assessment, main backend record, and checklist resolved.

## Step 3 dataset scope — 10 November 2026

- The user confirmed the data is already settled in the database and requested the first runnable path, with meeting and deliberately impossible-arrangement scenarios deferred.
- Accepted the existing database as the source for rooms, lecturers, students, memberships, courses, offerings, sections, weekly teaching requirements, and any existing class bookings. Initial generation does not require pre-existing bookings.
- Reviewed the existing seed/setup documentation and course seed. Those cover core identities, memberships, room inventory, and six teaching components for the sample intake. Actual hosted row values and teaching periods were not independently queried or audited.
- Step 3 is data preparation, so no new application code, migration, synthetic-data generator, or additional seed script is needed. Existing seed scripts were not rerun and no hosted data was changed.
- Specialized room-scarcity/undersized-room fixtures are optional later enhancements rather than blockers for the first runnable path. Meeting and impossible-arrangement fixtures are explicitly deferred. Later conflict validation and accurate infeasibility reporting remain planned behavior.
- Updated `task_hayden.md` and [dataset readiness and scope](scheduling-dataset.md). Step 3 is complete for the agreed MVP scope; step 4 remains the next unimplemented milestone.
- Verification: documentation links and `git diff --check` are checked for this documentation-only update. Runtime/database tests were not rerun, and prior test results are not evidence of live database readiness.

## Required-room-type removal SQL - 10 November 2026

- User deferred course-offering changes and accepted removing `class_sections.required_room_type`, requesting concise SQL for manual execution and leaving their schema fix log to them.
- Prepared [a transactional database patch](../../supabase/migrations/202611100002_remove_required_room_type.sql) that updates dependent views and optional teaching-plan trigger references before removing the column, without CASCADE or deleting records. `schema.sql` and hosted Supabase were not changed.
- [SQL-only removal notes](required-room-type-removal.md) distinguish the prepared patch from remaining work: current Python requirements reader, old course seed/migration, fresh setup, and ERD still need coordinated adaptation. System-defined room suitability is not implemented by the SQL patch.
- Verification: 25 PostgreSQL/PGlite checks passed for the patch, including optional teaching-plan support, preserved data/protections, access grants, reruns, and safe rollback. No backend runtime suite or live database execution was performed.

## Step 4 implementation — 10 November 2026 (initial design; superseded 11 November)

- Implemented [the scheduling-data loader](scheduling-data-loader.md) as an internal backend function, `load_scheduling_snapshot(db, settings, week_start)`.
- Added `202611100003_scheduling_snapshot.sql`: a STABLE, security-invoker, service-role-only function returning one complete weekly JSON payload. Requirements, group rosters, lecturer references, room inventory, and overlapping bookings use one database read snapshot instead of independent requests. The migration requests a PostgREST schema-cache refresh and does not insert or modify scheduling records.
- Resolved actual student UUIDs through intake/group memberships, with deduplicated counts and preserved identities across intakes. Student names/codes and lecturer names are not fetched for the engine.
- Loaded all target-week demand with an explicit pending subset, fixed class bookings (including legacy/unlinked bookings and existing reservations), and any scheduled meeting attendance. Empty meetings are supported; no hosted meeting fixtures were required.
- Used exact half-open overlap checks across week boundaries, excluded cancelled bookings, and derived/validated class end times from duration. Existing bookings are not assumed to satisfy calendar or room suitability rules simply because they exist.
- Added immutable engine models, effective configured opening windows, aware UTC instants, input validation, and a content fingerprint independent of source ordering/capture metadata. This is a captured input, not a booking lock; step 10 must revalidate it.
- Extended the existing Supabase transport for the JSON-object RPC. Missing RPC/access/upstream failures are explicit 502 errors; timeout is 504; invalid scheduling data raises safe structured `SchedulingDataError` categories.
- Adapted the older weekly reader to accept views before/after the accepted `required_room_type` removal patch. That field is optional legacy metadata; course type and actual room types remain available. No replacement compatibility policy or offering end date is inferred. The older course seed and initial schema remain user-managed as previously documented.
- Added local SQL fixtures/tests and HTTP integration tests using JSON generated by the real PostgreSQL function. Verified both migration orders relevant to the optional room removal, plus cached-view recreation after a prior snapshot read.
- Verification: **32** new snapshot SQL checks; **53** focused loader/weekly-reader tests; full backend suite **96 passed, 1 optional simulation test skipped**, with one existing deprecation warning. All six SQL suites passed (**258 database checks total**). `git diff --check` and documentation links passed.
- Used the existing ignored local Python/PGlite test tooling. Postman CLI is unavailable; the existing CLI mock still covers only the rooms probe. The new transport was exercised through a temporary local HTTP stand-in, not a deployed mock or hosted provider. No hosted data was queried or changed.
- Updated the checklist, root/database README, detailed loader notes, simulation evidence record, and room-removal compatibility notes. At that date, the implementation depended on applying the snapshot RPC migration; that deployment instruction was superseded by the 11 November direct-read implementation. Availability/conflict validation was step 5 and is recorded below.

## Step 5 implementation — 10 November 2026

- The user confirmed the room mapping: lectures may use classrooms or auditoriums; tutorials and labs may use classrooms or labs. Added `scheduling.room_compatibility` to tracked configuration. `others` starts with an empty mapping and is rejected until explicitly configured.
- Added typed configuration and immutable `RoomRule` values to the scheduling snapshot. Input fingerprints include the captured policy. (The original single-RPC transport was replaced on 11 November; see the superseding entry below.)
- Implemented `BookingProposal`, `BookingIssue`, `BookingValidation`, `BookingValidator`, and `validate_booking` in `backend/app/scheduling/validator.py`. Duration, lecturer, and roster come from the trusted occurrence; callers cannot override them or provide arbitrary booking exclusions.
- Validate selected-week bounds, complete duration within opening hours, active/suitable/sufficient-capacity room, and room/lecturer/student overlap against fixed classes/reservations and meetings. Student conflicts compare actual UUID sets across intakes. Rejections report booking references and counts without listing private student UUIDs.
- Preserve unrestricted start times, seconds/fractional seconds, adjacent classes, and no mandatory breaks. Rescheduling ignores only the selected occurrence's matching original class; a meeting with the same UUID is still checked. Cancelled demand must be explicitly reopened; duplicate scheduling is rejected.
- Validation is pure and creates no booking, reservation, or authorization. It evaluates one proposal against one captured week. Cross-week target preparation, mutual constraints among generated classes, and transactional revalidation remain later steps.
- Verification: **52 focused validator tests passed**; full backend suite **148 passed, 1 optional simulation test skipped**, with one existing test-client deprecation warning. The loader integration test uses real local PostgreSQL output over HTTP and now exercises cross-intake student conflicts through validation. A policy-change test verifies the snapshot fingerprint changes. No SQL source changed in step 5, so prior 258-check database results were not rerun or presented as new evidence.
- Updated the backend notes, checklist, README, room-removal notes, and working instructions with the confirmed policy. No hosted data was queried or changed, no new SQL migration was added, and no public endpoint was exposed. Details: [booking validation](booking-validation.md).

## Step 6 implementation — 10 November 2026

- Implemented `CandidateGenerator`, `generate_candidates`, and `generate_weekly_candidates` in `backend/app/scheduling/candidates.py`. Results describe complete feasible start ranges per occurrence and room, plus diagnostics, captured horizon, and input revision.
- Preserved unrestricted starts using inclusive earliest/latest bounds at datetime microsecond precision. Exact-fit free gaps yield one valid start. No grid, rounding, arbitrary suggestion limit, or domain truncation is introduced.
- Refactored `BookingValidator` to share lifecycle checks, static room eligibility, and resource-blocking intervals with the generator. The ordinary validation API continues using those same rules. Existing validator checks remained passing.
- For each eligible room/window, clip fixed class/reservation/meeting blockers, merge overlapping or adjacent busy periods, and subtract them. Only uninterrupted gaps at least as long as the class produce ranges; different teaching windows are not stitched together.
- Retained actual cross-intake student conflicts, cancelled-booking exclusion, and reschedule exclusion limited to the occurrence's matching original class. A meeting with the same UUID remains blocking.
- Added explicit no-candidate explanations for missing occurrence/lifecycle, no open windows, excessive duration, absent/unsuitable rooms, and insufficient uninterrupted availability. Supporting booking diagnostics are not represented as a minimum infeasibility explanation or a global timetable proof. Diagnostics can also explain excluded rooms when other rooms remain feasible.
- Weekly generation processes only pending occurrences, preserving independent possibilities for step 7's joint solver. It does not book a room or consume one lesson's choices while evaluating another. Empty pending input stays explicitly empty.
- Verification: **24 new candidate test cases**, with **76 combined candidate/validator tests passed**. Full backend suite: **172 passed, 1 optional simulation test skipped**, in 54.61 seconds, with one existing deprecation warning. Tests compare generated ranges with validation at boundaries and sampled fractional-second starts, and exercise the full real local PostgreSQL-output → HTTP loader → validator → generator path, including removed-room-column compatibility.
- No SQL source or provider interaction changed. No new migration, public endpoint, hosted query/write, or sample-data requirement was introduced. Existing local test tooling was reused. SQL suites were not rerun solely for this pure computation change. Documentation links and `git diff --check` passed.
- Updated the checklist, README, and [candidate-generation design/usage notes](candidate-generation.md). Step 7 (joint CP-SAT generation) remains the next unimplemented milestone.

## Step 7 implementation — 10 November 2026

- Added `ortools>=9.14,<10` to backend requirements and installed OR-Tools **9.15.6755** with dependencies in the ignored local project environment. No global Python configuration was changed. Verification used the existing local CPython runtime and approved execution because the restricted context could not read the newly installed package directory.
- Implemented `solve_weekly_schedule` in `backend/app/scheduling/solver.py`. It generates candidates internally from the trusted snapshot and assigns every pending lesson jointly, with one mandatory class interval and exactly one room choice.
- Encoded time as integer microseconds relative to the selected week's UTC start using integer timedelta division. Candidate boundaries and class duration are preserved exactly, including fractional seconds; no teaching-slot grid is imposed.
- Restricted each selected room to its own union of candidate start domains. Added no-overlap for shared lecturers, room choices, and actual students across intakes. Identical student lesson signatures share one equivalent constraint for efficiency without losing membership conflicts.
- Existing bookings, reservations, and meetings remain fixed through candidate domains. The model does not add an unrelated requirement to repair overlaps among already-existing legacy bookings. It never changes the snapshot or writes bookings.
- Added typed `SolverSettings` under `scheduling.solver`: default 10-second search, one worker, seed 0. These control search and are recorded in result statistics; they do not alter physical scheduling-input fingerprints.
- Added immutable placements/results, counts, diagnostics, candidate failures, and solver statistics. Statuses distinguish `OPTIMAL`, `FEASIBLE`, `INFEASIBLE`, `UNKNOWN`, `MODEL_INVALID`, and explicit `NO_PENDING_REQUIREMENTS`. No candidates proves failure for the captured input without invoking CP-SAT; unresolved search is never described as impossible.
- Successful extraction must cover every pending identity exactly once. The validator checks each assignment against fixed input, and a separate pairwise check detects resource conflicts among generated classes. A verification disagreement raises an internal error instead of returning unsafe assignments.
- This step solves feasibility. OR-Tools `OPTIMAL` can mean the zero-objective feasibility model is solved; student-gap/lecturer-gap/room-use optimization remains step 8. The synchronous engine produces a draft and introduces no public endpoint, authorization, or persistence operation.
- Verification: **29 focused solver cases passed**. Full backend suite: **201 passed, 1 optional simulation test skipped**, in 59.27 seconds, with one existing test-client deprecation warning. Coverage includes joint conflicts, independent parallel classes, scarce-room allocation, room/start-domain linkage, exact fractional-second starts, fixed-booking preservation, complete-only outcomes, actual tiny-budget `UNKNOWN`, and a six-component/40-student weekly case. `FEASIBLE` labeling and invalid-model/verification-error branches use explicit fault injection with real solving where applicable.
- Extended the real local PostgreSQL-output → HTTP snapshot → candidate → solver integration, including the schema without legacy room requirements. No additional provider request is made during solving. No SQL source changed, so earlier standalone SQL-suite results were not rerun or represented as new evidence. No hosted data was queried or changed.
- Updated the checklist, root README, candidate notes, and [solver setup, interface, and verification](cp-sat-scheduling.md). Documentation links and `git diff --check` passed. Step 8 is the next unimplemented milestone.

## Step 8 postponement and step 9 discussion - 10 November 2026

- The user postponed timetable quality improvements and requested discussion of step 9. Step 8 remains incomplete future work; the existing step 7 feasibility solver is the basis for the next milestone.
- Added [the preview API proposal](schedule-preview-api.md), describing a Monday-week request, fresh snapshot loading, worker-based solving, typed complete results, safe diagnostics, explicit lack of quality optimization, and no booking writes. It is a proposal, not an implemented API.
- Recommended a single request/response operation using server-configured search limits and scheduling all pending occurrences jointly. Recommended no new preview persistence in this read-only milestone; step 10 still needs trusted draft handling and transactional revalidation. Input revision alone is neither authorization nor a resource lock.
- Asked the user to confirm all-week versus intake/group generation and local-development access versus administrator authentication now. Both decisions remain open. Existing authentication integration is absent; an unrestricted deployed campus-wide endpoint is not proposed.
- Updated the roadmap, solver remaining-work notes, and checklist to reflect postponed quality work and the step 9 discussion. Corrected the obsolete project-direction statement that the solver was still uninstalled/unimplemented.
- No application code, configuration, SQL, hosted data, or runtime behavior changed. Runtime/database suites were not rerun for this documentation-only task.
- Verification: `git diff --check` passed; all **32 local documentation links** across the four changed/new Markdown files resolved. The first link-check script mishandled the root checklist's empty parent path; it was corrected to use absolute file paths and rerun successfully.

## Step 9 implementation - 10 November 2026

- The user requested implementation based on the proposal and a very simple page hosted on the same service at `/development/scheduling-test-hayden`. Applied the proposal's recommended whole-week scope, server-controlled search options, single request/response, no preview storage, and local-development access while administrator authentication remains deferred. Earlier discussion questions are superseded by these implementation defaults; intake/group filtering and remote/admin access are not implemented.
- Added `backend/app/scheduling/preview.py` and mounted its router. `POST /api/schedules/generate` validates an exact Monday date, rejects extra input fields, loads a fresh snapshot, runs the verified engine in a worker, and returns complete typed results with readable course/room labels from the same snapshot. No additional provider lookup is needed for labels. Student identity lists and raw snapshots are excluded.
- Responses preserve solver outcomes, revision, counts, diagnostics, and search statistics. `quality_optimized=false` and `quality=null` explicitly reflect postponed step 8. Infeasible, unknown, and empty-week outcomes return 200 without partial assignments. Safe structured errors distinguish invalid requests, missing configuration, provider failures/timeouts, malformed input data, invalid models, internal failures, and busy generation.
- Bound the complete load/solve/verify operation to one request per process; further requests receive 429 with `Retry-After`. Worker offloading keeps health requests responsive. AnyIO cancellation shielding retains the slot through normal scoped cancellation while the worker finishes. This is not distributed concurrency control or a booking lock. Added an explicit AnyIO dependency.
- Restricted API, HTML, JS, and CSS to `app.environment=development`, loopback peer and Host, approved browser Origin when present, and no forwarding headers. This deliberately does not support reverse-proxy/remote access. CORS now permits POST for configured origins; CORS is not the access boundary. Administrator authentication remains future work. Responses/page assets use no-store headers; HTML includes a self-only content policy.
- Added the plain HTML/CSS/JS test page, served independently of the Vue build. It selects a Monday using configured campus timezone, sends a same-origin request, disables controls during work, and renders new placements in campus-local time (including fractional seconds), status/counts, candidate diagnostics, revision, and raw JSON. It distinguishes empty/infeasible/unknown outcomes and recovers controls after request failures. Provider labels are inserted as text rather than HTML.
- Verification: **29 focused API tests passed**; **230 full backend tests passed, 1 optional simulation test skipped**, in 76.79 seconds, with one existing Starlette/httpx deprecation warning. Tests cover the actual local PostgreSQL-output to HTTP loader to real solver to API response path, error privacy, no booking writes, access restrictions, explicit failures, configured options, busy responses, and responsiveness during solving. An initial infeasibility-response failure exposed nested computed-field serialization; round-trip model dumping corrected it and the suite passed afterward.
- **10 Node/jsdom page tests passed** in 1.78 seconds, including actual served HTML/JS making a real HTTP request to a synthetic provider-backed solver service and rendering both a valid preview and an empty subsequent week. Other cases cover date validation, UTC-to-campus display with microseconds, text-only labels, unknown/infeasible outcomes, progress, stale-view hiding, malformed responses, busy errors, and network failures. This establishes DOM/request behavior, not visual layout or real-browser policy enforcement.
- Browser UI verification was attempted, but native browser-app access approval timed out. No visual/browser success is claimed. Used an isolated ignored jsdom 26 installation and existing Python/PGlite tooling; no global tooling changed. Added a reproducible synthetic UI QA server in `backend/tests/serve_schedule_preview.py`. No live Supabase request, migration, sample insertion, or booking write was performed.
- Started the actual FastAPI service on `127.0.0.1:8000` for the requested page. A separate temporary synthetic service on port 8001 was used only for UI verification. Existing hosted migrations/data must still be ready before live generation succeeds. No public/cloud deployment was performed.
- Updated the checklist, README, [implemented API/page notes](schedule-preview-api.md), solver remaining-work notes, and simulation evidence. Step 9 is complete locally; step 10 safe saving remains unimplemented and step 8 remains postponed.
- Final verification: the checked-in synthetic UI QA helper started successfully and all 10 page checks passed again (1.70 seconds). The actual service returned HTTP 200 for the requested page on port 8000. Stopped the temporary port-8001 QA service after testing; port 8000 remains running. All **46 local documentation links** across five changed/new Markdown files resolved; JavaScript syntax and `git diff --check` passed. Postman CLI remains unavailable; no CLI simulation run is claimed.

## Step 9 confirmed intake/group scope - 10 November 2026

- The user's delayed answers confirmed **only a selected intake/group** and **local development first; administrator authentication later**. This supersedes the whole-week implementation default recorded above.
- `GenerationRequest` now requires an intake UUID. An optional positive integer group number narrows that intake to one group; omission/null includes all groups in that intake. No campus-wide generation fallback is exposed by this endpoint. Non-integer, boolean, nonpositive and invalid UUID inputs are rejected.
- Added `select_scope` after the existing validated weekly load. Only matching requirements reach the solver. All fixed class/meeting/reservation intervals, student attendance identities, room inventory, and calendar/policy values are retained. Pending demand outside the selection is not scheduled or treated as a reservation. The loader still validates the complete source; malformed unrelated source data can still reject loading.
- Derived preview revisions from the full source fingerprint plus intake/group selection. Response metadata identifies `intake` or `intake_group`, the intake UUID and optional group. Distinct scopes have distinct revisions even when empty; repeated selection of unchanged inputs remains stable. Step 10 must preserve this scope when revalidating a reviewed draft.
- Updated the test page with required intake UUID and optional group inputs, validation, scoped POST payloads, scope display, and scoped empty-state text. This intentionally uses database IDs directly; no catalog endpoint or new provider call was added. A valid-looking selection without demand returns `NO_PENDING_REQUIREMENTS`; existence is not queried separately.
- Verification: **38 focused API tests passed**; full backend suite **239 passed, 1 optional simulation test skipped**, in 92.10 seconds, with one existing Starlette/httpx deprecation warning. New checks cover filtering across intakes/groups, all selected intake groups, unrelated impossible pending demand, required/valid scope fields, retained cross-intake student blockers, and scope-bound revisions. **11 Node/jsdom page tests passed**, including the real served page/request/response path and intake/group input behavior. Visual browser and live hosted database readiness remain unverified.
- No SQL, hosted data, booking persistence, or authentication behavior changed. Restarted the development service on localhost:8000 with the selected-scope code. Updated working instructions, API notes, README, checklist, and simulation evidence; authentication and trusted saving remain future work and quality optimization remains postponed.
- Final checks: the running port-8000 page returned HTTP 200 with intake/group inputs, and its OpenAPI contract requires `intake_id`. Stopped the temporary synthetic port-8001 service after UI checks; port 8000 remains running. All 46 local documentation links across six reviewed Markdown files resolved; JavaScript syntax and `git diff --check` passed. Postman CLI remains unavailable; HTTP tests used the existing local provider stand-in.

## Development startup port conflict investigation - 10 November 2026

- The user reported Windows bind errors 10013 (reload invocation) and 10048 (plain invocation) on port 8000 and asked whether permissions were responsible.
- Read-only inspection confirmed `127.0.0.1:8000` is already owned by Python PID 39544, matching the project-local runtime and Uvicorn command started during the previous task. `GET /api/health` returned `status=ok`, `service=SClass`. Listener/process inspection required approved execution; the health check succeeded directly.
- The confirmed blocker is an existing healthy service occupying the address. Microsoft also documents exclusive address ownership as a possible cause of 10013, consistent with the first error; that first failing bind was not separately reproduced. No firewall/permission changes are indicated by the verified conflict.
- Left the existing service running because the user requested diagnosis. Documented reuse or identifying/stopping the prior process before restarting, with troubleshooting commands in [the preview setup notes](schedule-preview-api.md). No application/configuration/database behavior changed; runtime suites were not rerun for this investigation.

## Scheduling failure tracing and live RPC diagnosis - 10 November 2026

- The user reported the development page's HTTP 502 with upstream Supabase 404 and asked for logging to trace the failure. Prior access logs/general exception handling did not provide correlated stages or preserve a safe provider error code.
- Two read-only checks against the configured project confirmed **HTTP 404/PGRST202** for `load_scheduling_data`, including a complete local API request using the current code. No snapshot or private records were returned; no solver ran. This proves the matching function is unavailable through PostgREST's schema cache, not whether the migration is absent versus the cache/signature being stale. No hosted SQL, cache notification, grant, or booking change was executed. Hosted generation remains blocked on RPC setup.
- Added `backend/app/observability.py`: scoped ASGI request correlation, server-generated UUIDs, `X-Request-ID`, JSON console and rotating `logs/scheduling.log` output. The active file rotates at 5 MiB with two backups; `logs/` is ignored and not served. File permission failure retains console output with a safe warning. Setup is idempotent per process; shared multi-process rotation/log aggregation remain future work.
- Logged safe RPC and load/solver stages, counts, outcomes and durations. Middleware captures final status for success, validation, access and busy errors without logging request contents. Structured errors include the request ID; approved CORS clients can read the response header. The page displays both classification and request ID on errors and shows trace IDs on normal outcomes.
- Added `SupabaseRPCError` with allowlisted provider-code retention and actionable `SCHEDULING_RPC_NOT_FOUND`, `DATABASE_PERMISSION_DENIED`, and `DATABASE_SCHEMA_INCOMPLETE` classifications. Generic failures/timeouts retain safe behavior. Raw provider messages/details/hints, URLs, keys, headers, rosters, student/intake IDs, names, parameters, and snapshots are not recorded by the new channel. Unexpected failures record exception type and stack locations without exception text, source lines or locals; unstructured logger messages are suppressed.
- Verification: **47 focused logging/API tests passed**; **248 full backend tests passed, 1 optional simulation test skipped**, in 99.50 seconds, with one existing Starlette/httpx deprecation warning. Tests inject private-looking provider errors and exception messages and verify correlation, classification, stage sequencing, response/log privacy, handler idempotence and safe file-permission fallback. **12 Node/jsdom page checks passed**, including served-page HTTP behavior and error-code/request-ID display. Visual browser verification remains unverified.
- The configured live failed request was recorded in the actual console/file log, confirming end-to-end trace correlation. No SQL source changed; standalone SQL suites were not rerun. The existing HTTP integration fixtures execute real SQL locally. Postman CLI remains unavailable, so verification used those existing controlled HTTP fixtures rather than a CLI simulation.
- Added [logging usage, privacy rules, and database setup diagnosis](scheduling-logging.md), including read-only existence SQL, prerequisite/snapshot migration links, and cache-refresh guidance. Updated API contract documentation, README, checklist, and simulation evidence. The current user's port-8000 process was not stopped or replaced; restart it to load backend changes. A temporary synthetic port-8001 service was used only for verification.
- Final checks: confirmed all five events for the live failed diagnostic request exist in the file log; stopped the temporary port-8001 service without changing the user's server. Active and rotated log paths are Git-ignored. All 55 local links across five updated/new documentation files resolved; JavaScript syntax and `git diff --check` passed. Unrelated student-document working-tree edits were left untouched.

## Step 4 backend-owned data loading — 11 November 2026

- In response to the user's direction, moved scheduling snapshot retrieval and assembly out of the `load_scheduling_data` SQL function and into `backend/app/scheduling/loader.py`.
- The backend now reads `teaching_occurrence_details`, `class_session_details`, `class_sessions`, `meeting_sessions`, `meeting_students`, `student_intakes`, `rooms`, and referenced `lecturers` using the existing server-only Supabase client. It filters by week, resolves exact intake/group rosters, attaches meeting attendees, preserves cross-intake conflicts, and paginates reads at 500 rows.
- Removed the schedule path's RPC transport and RPC-specific `SCHEDULING_RPC_NOT_FOUND` branch. Safe logs identify the fixed read stage and row count or exception type, without query values, identifiers, rosters, credentials, or provider bodies.
- The migration `202611100003_scheduling_snapshot.sql` remains in history, but backend generation no longer depends on it. Step 2's teaching-requirement migration/views and the existing source schema remain necessary.
- **Consistency tradeoff:** independent PostgREST requests do not share one PostgreSQL MVCC snapshot. `captured_at` records the end of data collection; `database_snapshot` is now a descriptive capture marker, not a transaction snapshot ID. Step 10 must re-read and validate transactionally before any booking write.
- Updated focused HTTP-provider fixtures and documentation. Tests and hosted database calls were not run for this implementation. Hosted permissions, required relation availability, and live scheduling behavior remain unverified.

## Step 2 room-policy schema compatibility — 11 November 2026

- The user requested completing Step 2 after `class_sections.required_room_type` had been removed and room suitability had moved into backend configuration.
- Updated `202611100001_teaching_requirements.sql`: its metadata-protection trigger now protects only section offering/group metadata, and `teaching_occurrence_details` no longer selects `required_room_type`. The migration is designed to work whether the optional room-removal patch ran before or after it.
- Updated `load_weekly_requirements` to explicitly select the Step 2 contract fields, so it works against either older views that still contain the legacy column or the updated view without it. Removed the legacy field from the `TeachingOccurrence` model; room policy remains solely in `Config/config.json` and the scheduling snapshot.
- Updated Step 2 and database setup documentation. No database script was applied to a hosted project.
- **Verification at the time:** the migration, backend, and database tests were not run for this compatibility change. The migration should be applied once only after checking its dependent base tables; existing `teaching_plans`/`teaching_occurrences` or an existing Step 2 migration entry mean do not rerun it. See [weekly-plan setup](weekly-teaching-plans.md) and [room-field removal notes](required-room-type-removal.md).

## Step 2 completion — 11 November 2026

- The user confirmed that Step 2 is complete and asked for the documentation to be updated. Updated the roadmap, the checklist, the weekly-plan notes, the room-field removal notes and the root README.
- Completion rests on the user's confirmation. This documentation-only task did not run the backend or database suites, query the hosted project, or apply any SQL. The user chose not to run the test suite in this session. The latest automated Step 2 results (16 focused reader, 59 full backend, 201 database checks) still predate the 11 November compatibility edit.
- Deferred items are follow-ups, not blockers for Step 2: offering end dates, automatic holiday/semester-break handling, applying `202611100002_remove_required_room_type.sql` to the hosted database, adapting the legacy course seed and fresh setup, and updating the ERD.
- Step 4's direct-read loader and the Step 9 preview that depends on it still need verification.

## Step 10 saving plan and no-draft decision — 11 November 2026

- The user decided there is **no draft storage** in this phase. A preview exists only on the page; leaving or reloading loses it and the admin generates again. Saving writes real bookings immediately. Reason: hackathon scope and shipping quickly.
- Saved placements go into the existing `class_sessions` table (one row per placement: occurrence, section, room, start, `scheduled`). Other users see them through `class_session_details` under existing row-level security; the student timetable endpoint already reads it. No new table is needed.
- Drafted a saving plan with seven open decisions (who may save, stale-preview handling, concurrency strength, audit, whole vs partial save, viewing, undo). It was planning only; the decisions and implementation are recorded in the next entry, and the plan file became [timetable saving](timetable-saving.md).

## Step 10 implementation — 11 November 2026

- Work done on a new branch `backend-step10-save-timetable`, created from an up-to-date `main` at the user's request. The user limited scope to the backend and the `development/` test page; no student, lecturer or admin frontend code was touched.
- **Decisions confirmed by the user:** admin only (enforced by the existing development/localhost checks until login exists); reject a stale preview and regenerate; backend recheck then one insert, accepting the race with outside writers instead of a database function; audit deferred until the login page exists; whole preview only; viewing saved timetables out of scope; no undo, with a double confirmation on saving recorded as a design remark for the admin frontend.
- Added `POST /api/schedules/save` (`backend/app/scheduling/save.py`, `preview.py`). It shares the generation slot and access checks, re-reads the week, requires the same scope-bound revision, requires every pending class exactly once, revalidates each class and their mutual clashes with the existing validator and solver verification, then writes all rows to `class_sessions` in one PostgREST insert. Section, lecturer, duration and roster come from the database, not the client. Errors are classified without provider text; write timeouts are reported as an unknown outcome.
- Added `Supabase.insert` and `SupabaseWriteError` to the shared client in `backend/app/student.py`; made the solver's placement verification public (`verify_placements`, old private name kept as an alias); extended request tracing to the save path.
- Development page: a save panel shown only for a complete preview, with a two-step confirmation (summary, then a required acknowledgement tick box). Notice text now says previews are not stored and saves cannot be undone.
- Tests: extended the shared fake Supabase in `test_scheduling_loader.py` with a `class_sessions` insert (separate `writes` record, so existing read assertions are unchanged); added `test_schedule_save.py`; added save-flow page tests; gave the synthetic QA server (`serve_schedule_preview.py`) a minimal insert handler.
- **Verification:** 30 new save API tests passed. 19 page tests passed (Node/jsdom), including a served-page save through the real backend against the synthetic QA service on port 8001, which was stopped afterwards. Full backend suite: **170 passed, 10 failed, 95 errors, 1 skipped**, compared with **140 passed** and the **same** 10 failures and 95 errors on `main` before this work. Those pre-existing problems are stale fixtures (removed `required_room_type` field; pre-direct-read RPC expectations) and were not changed here.
- Not verified: a save against hosted Supabase, visual browser rendering, multiple server processes. No hosted data, schema, migration or grant was changed.
- Observed but not changed (out of scope): `backend/app/lecturer.py`'s reschedule endpoint writes `class_sessions` directly without validation or the scheduling slot. The scheduling API quick guide (`scheduling-api-guide.md`) is on the unmerged `backend-development-hayden` branch, not on `main`, so it was not updated here.

## Login and role-based access — 12 November 2026

- Work done on branch `feature-login`, created from an up-to-date `main` (which includes step 10 via PR #9) at the user's request.
- **Requirement:** everyone logs in at `/login` with Supabase account credentials; roles are admin, student and lecturer; every page that needs a login redirects to `/login`.
- **Decisions confirmed by the user:** email + password (Supabase Auth); accounts created and linked by the project owner, not the app; backend-handled login with httpOnly cookies; pages `/student`, `/lecturer`, `/admin`; role priority admin > lecturer > student; main menu removed and `/admin` left as an empty placeholder for another team member; student and lecturer pages unchanged apart from routing to them; sign-up and password reset out of scope; development pages moved under `/admin` and admin-only. Details and reasons: [login](login.md).
- **Implemented:** `backend/app/auth.py` (login/logout/me, Supabase token verification with a 60-second cache, automatic refresh, cookie middleware, role lookup, `require_roles`); server-side page redirects in `main.py`; access checks for the student, lecturer, database-health and scheduling endpoints. The lecturer reschedule endpoint now also checks that the class belongs to the lecturer (previously anyone could move any class). Frontend: a small path router, login page, empty admin page, session bar with log out, and a redirect to `/login` when any API call returns 401.
- **Verification:** 23 new backend auth tests passed; full backend suite 193 passed with the same 10 pre-existing failures and 95 errors as `main`; 7 new frontend tests and the 12 existing lecturer tests passed; `npm run build` succeeded; 19 scheduling page tests passed, including served-page tests that log in as a synthetic admin. Not verified against hosted Supabase or in a real browser.
- **Follow-ups:** create and link accounts in Supabase (steps in [login](login.md)); save audit using the logged-in admin; the student/lecturer page READMEs still mention `#/` addresses (owned by those pages' authors).

## Vercel services deployment — 12 November 2026

- Work done on branch `feature-vercel-services`, created from `main` at the user's request.
- **Requirement:** deploy the repository on Vercel as one project with services, using a root `vercel.json`.
- **Implemented (pending the user's confirmation of names and routing):** services `backend` (`backend/`, FastAPI, entrypoint `app.main:app`, public at `/api/*`) and `frontend` (`frontend/`, Vite, public catch-all with an `index.html` fallback for the Vue path router). No bindings, because no service calls another from server-side code; the browser calls same-origin `/api/...`. `/admin/development/*`, `/docs` and `/openapi.json` are not publicly routed.
- **Code change:** a backend service rooted at `backend/` does not deploy `Config/config.json`, so its build step copies the file into `backend/Config/`, and `default_config_path()` falls back to that copy only when the repository copy is missing. `Config/config.json` remains the single source of truth. Details and reasons: [Vercel deployment](vercel-deployment.md).
- **Verification:** new config-path test passed; full backend suite 194 passed with the same 10 pre-existing failures and 95 errors as `main`; `npm run build` succeeded; a simulated backend-only bundle served `/api/health` and `/api/config`. `vercel dev` and a real deployment have not been run.
- **Follow-ups:** confirm service names/public paths/bindings; set `SUPABASE_URL` and `SUPABASE_KEY` in the Vercel project; run `vercel dev` and a preview deployment; check bundle size, the SPA fallback and the cookie `Secure` flag on Vercel.

## Step 10 save audit — 12 November 2026

- Work done on branch `backend-enhancement` at the user's request (A7).
- **Requirement:** with login in place, record who saved a timetable, together with the classes in one transaction (the deferred D4).
- **Decisions (user accepted every recommendation):** a database trigger writes the audit, so the backend keeps one insert (A1); one `schedule_changes` `create` row per class (A2); inserts without an admin are allowed but not audited (A3); audited classes cannot be deleted (A4); the student endpoint ignores `create` rows (A5); the audit is viewed with SQL only (A6).
- **Implemented:**
  - Migration `202611120002_save_audit.sql`: `class_sessions.created_by`, `create` action, AFTER INSERT trigger.
  - The save sends the admin's Supabase user id. `SessionUser.auth_user_id` is server-side only. The response adds `saved_by`. A missing migration returns `503 AUDIT_NOT_INSTALLED`.
  - Student recent changes are filtered to `cancel`/`reschedule`.
  - Details: [save audit](save-audit.md).
- **Verification:**
  - 46 new database checks passed.
  - Full backend suite: 199 passed, with the same 10 failures and 97 errors as before.
  - 19/19 page tests passed, including a real save on the QA service.
  - Not run on hosted Supabase.
- **Follow-ups:**
  - The user runs the migration before deploying this backend.
  - Lecturer reschedule auditing belongs to step 11.

## Step 8 review and plan — 12 November 2026

- The user asked to check step 8 (quality optimization), confirm what is done, and plan the work. Review result: none of step 8 is implemented. The solver has no objective; the preview returns `quality_optimized: false`, `quality: null`.
- The solver tests that step 8 would extend currently error because of the stale `required_room_type` fixture.
- Plan, risks and open decisions Q1–Q8 were written the same day; the plan has since been replaced by the implementation record [timetable quality](timetable-quality.md).

## Step 8 implementation — 12 November 2026

- Work done on branch `backend-enhancement` (Q8).
- **Decisions:** Q1 whole-minute starts (changes the accepted "any time" rule); Q2 weighted sum 100/10/1; Q3 auditoriums only when no other permitted room can seat the class (compulsory) plus fewer empty seats (preference); Q4 report the longest day only; Q5 10 s; Q6 config only; Q7 fix fixtures first.
- **New requirement from the user:** a 15-minute gap between scheduled classes. Implemented as compulsory for any two bookings sharing a room, lecturer or student, including meetings (interpretation recorded for confirmation).
- **Implemented:** the rules in the shared validator, candidates and solver; a two-phase search with the weighted objective; `quality` measurements in every complete result; the page shows them. Details, example and risks: [timetable quality](timetable-quality.md).
- **Verification:** 37 new tests; full backend suite 335 passed with the same 10 pre-existing failures and 0 errors (previously 97 errors from the stale fixture, now fixed); 20/20 page tests including the served QA run; not run on hosted Supabase.
- **Follow-ups:**
  - Confirm the two interpretations (gap scope, capacity-based auditorium rule).
  - Decide whether to add a "fewer days on campus" preference.
  - Check preview time on hosting.
- **Time limit raised (12 November 2026):** at the user's request `scheduling.solver.max_time_seconds` is now 120 s (was 10 s). **Raised again to 280 s on 13 November 2026, then set to 60 s the same day** (see those entries). An unlimited value is not supported (0 and infinity are rejected at startup). With preferences on, a preview can take up to about 2 minutes plus loading time, holding the one-at-a-time slot.

## `main` merge repair — 12 November 2026

- **Problem:** merging the Admin branch (PR #13) left unresolved conflict text on `main` in `backend/app/main.py` (`SyntaxError`, the backend could not start), `frontend/src/App.vue` and `frontend/src/admin/AdminPage.vue` (the frontend build failed). Found while validating step 11.
- **Work done on branch `fix-main-merge-conflicts`,** created from the updated `main` at the user's request.
- **Fixes:**
  - `main.py`: both the admin and lecturer routers are included. CORS allows GET, POST, PUT, PATCH and DELETE plus the `Authorization` header (admin page and lecturer reschedule), and still exposes `X-Request-ID`.
  - `App.vue`: restored to the login shell from before the merge. The merge had re-added the old main menu, `#/` routing and a duplicate `AdminPage` import, which login replaced on 12 November.
  - `AdminPage.vue`: the admin page from its author's commit `28c7609` ("Admin pages combined"); the earlier empty placeholder was dropped, as intended once the admin page existed.
- **Also changed (needed for the admin page to work with login):**
  - `backend/app/admin.py` accepts the logged-in admin's session cookie when no token is pasted; a pasted `Authorization: Bearer` token still works.
  - The admin timetable database functions run as that admin, using the session's access token. `get_session` keeps the verified access token on `request.state`, server-side only.
  - Before this, a logged-in admin could not use the page: their token is in an httpOnly cookie they cannot read, and a blank token returned 401, which sent them to the login page.
- **Tests:** the auth test fake now has the fields the lecturer reschedule code reads, a room table, a `schedule_changes` insert, `true`/`false` matching and paging. One test checks the reschedule log's `changed_by`; a new test covers admin API access with the login session.
- **Verification:** the backend starts and the frontend builds. Full backend suite: 337 passed, with the same 10 older loader/preview failures as before. The auth test broken by the merged lecturer code is fixed, and the new admin-session test passes. All 9 database test sets pass. Frontend: 12/12 lecturer and 7/7 login tests. Scheduling page: 20/20, including the served QA run. Not run against hosted Supabase or in a real browser.
- **Not changed (reported in the step 11 validation):** the admin page frontend still shows a token box; the admin reschedule database function ignores `rescheduled` classes when checking clashes (double-booking reproduced locally); the lecturer move does not check opening hours, room type, the 15-minute gap or the auditorium rule; cancellation and reservations are not built.

## `rescheduled` class-session status — 12 November 2026

- Work done on branch `backend-enhancement`, created from `main` at the user's request. The user will continue other work on this branch.
- **Requirement:** keep the database restriction on `class_sessions.status`, but add `rescheduled`, used when a lecturer or admin moves a scheduled class. The user first considered removing the restriction completely. They chose a specific value after reviewing the impact: unrestricted values would silently free the slot in the scheduler while the pages still showed an active class.
- **Decision:** `rescheduled` is an active booking that has been moved in place (`occurrence_id` is unique, so there is no second row). It blocks room, lecturer and students like `scheduled`, needs a room, and is not outstanding demand. Only `cancelled` releases a slot. Meetings are unchanged.
- **Implemented:**
  - Migration `202611120001_class_session_rescheduled_status.sql` (constraints, partial index, three step 2 trigger functions), plus matching `schema.sql`.
  - One shared status definition in `scheduling/requirements.py`, used by the loader and validator.
  - The lecturer/admin reschedule endpoint writes `rescheduled`, refuses cancelled classes with 409, and reports `moved` from the status.
  - Details, SQL and setup order: [rescheduled status](rescheduled-status.md).
- **Verification:**
  - New database test: 33 checks passed. All six existing database suites still pass.
  - New loader and updated auth tests passed.
  - The full backend suite has the same failures as `main` (10 failed, 95 pre-existing errors), plus 2 new validator tests. Those 2 error only because of the existing broken `required_room_type` fixture, and passed in a temporary corrected copy.
  - Not run on hosted Supabase.
- **Follow-ups:**
  - The user runs the migration on Supabase.
  - The lecturer endpoint still writes without validation or audit (step 11).
  - The validator fixture still needs fixing.
  - The unused `load_scheduling_data` RPC still filters only `scheduled`.

## Checklist removal, decisions and step 11 review — 12 November 2026

- Work done on `main` (after PR #15), uncommitted, at the user's request.
- **Checklist removed:** `task_hayden.md` was deleted because the work is nearly done. Its open items moved to [Remaining work](#remaining-work). Links to it were removed from `AGENTS.md`, the README and seven backend notes.
- **Decisions:** the user answered "yes" to all four open questions:
  - The 15-minute gap covers rooms, lecturers and students, including meetings.
  - The auditorium rule is judged by capacity, not availability.
  - The "fewer days on campus" preference and course-offering end dates were first recorded as accepted. Later the same day the user **deferred both** as not a priority, keeping scheduling as it is.
  - Recorded in `AGENTS.md`, [timetable quality](timetable-quality.md) and [offering end dates](offering-end-dates-and-room-policy.md).
- **Step 11 review:** the lecturer page's rescheduling was reviewed. The 13 findings are in the [review](lecturer-reschedule-review.md). High:
  - no opening-hours check;
  - no 15-minute gap;
  - no room-type or auditorium check (and the page lists only classrooms);
  - check-then-write without a lock or transaction.
  - The recommended fix is to reuse the snapshot, validator and candidate generator. Apart from the item below, the findings are not fixed.
- **Fixed:**
  - The lecturer timetable returned a hard-coded `intake_code` ("CS-2024") and `student_count` (30). It now returns the real intake code and group size (`group_facts` in `lecturer.py`), with a new test.
  - The admin reschedule database function read the removed `required_room_type` column (it fails once the removal patch is run). It also refused to move `rescheduled` classes and ignored them as clashes. The new migration [`202611120003_admin_reschedule_fixes.sql`](../../supabase/migrations/202611120003_admin_reschedule_fixes.sql) replaces it:
    - room type from the course type, following `scheduling.room_compatibility`, plus the auditorium rule;
    - both active statuses;
    - a moved class is marked `rescheduled`, with the status recorded in the audit.
    - Opening hours and the 15-minute gap are still not checked there.
  - `202611110001_admin_timetable.sql` previously failed on a database where the removal patch had already run. Its view now includes the legacy column only while the table has it.
  - The admin page's token box is labelled optional (the login session is used), rescheduled classes can be edited, and the dead "Main menu" link is gone.
  - README: removed the leftover merge-conflict text; updated the admin section (`/admin`, login, migrations), the start-time and gap rule, quality, login and the save audit.
  - Lecturer and student page READMEs: addresses, login and backend paths.
  - Stale "Current implementation" and "Open items" sections of this record were rewritten.
  - `docs/New Text Document.txt` (intake and group plan) is already implemented by `supabase/seed_students.sql`. One difference: the note lists the last cohort as `APD1F2507CS, APD2F2606CS(CYB)`, but the seed uses `APD2F2606CS` (without `(CYB)`), which looks like the intended value. The note was left as it is.
- **Verification:**
  - New database test `admin-reschedule-fixes.test.cjs`: 24 checks passed. It runs the removal patch both before and after the admin migration, and confirms the old function failed after the removal.
  - All 10 database test sets pass.
  - Backend auth/lecturer tests: 26 passed.
  - Full backend suite: 338 passed, 10 failed, 1 skipped. Before this work: 337 passed with the same 10 failures (the older loader/preview tests). The extra pass is the new lecturer test.
  - Frontend: 12/12 lecturer and 7/7 login tests; `npm run build` succeeds.
  - 130 local Markdown links resolve; `git diff --check` passes.
  - Not run against hosted Supabase or in a real browser.

## Deferred decisions, hosted setup scope and migration guide — 12 November 2026

- **Decisions:** the user deferred the "fewer days on campus" preference and course-offering end dates as not a priority, so scheduling stays as it is. Recorded in `AGENTS.md`, [timetable quality](timetable-quality.md) and [offering end dates](offering-end-dates-and-room-policy.md).
- **Hosted setup:**
  - Supabase account linking and the seed/fresh-setup/ERD updates are not needed (hackathon sample data).
  - The user reports that Vercel is set up and is used for production only. Scheduling previews and saves therefore stay on the local backend. Recorded in [Vercel deployment](vercel-deployment.md).
- **Migrations:** before the user runs them, added [hosted-migrations.md](hosted-migrations.md), which covers:
  - what each of the five migrations does;
  - the run order;
  - which ones can be rerun;
  - data loss (the room-type column) and a private backup;
  - what breaks without them.

  Also added the read-only status query [hosted-migrations-status.sql](hosted-migrations-status.sql). It was checked on local PostgreSQL (PGlite) before and after applying all five. Its first version wrongly reported `rescheduled` as applied on a fresh `schema.sql`, so it now also checks the trigger function. Nothing was run on hosted Supabase.

## Admin room timetable and `/admin/schedule` page — 12 November 2026

- Work done on branch `feature-admin-room-timetable`, created from `main` (after PR #17).
- **Requirement:** this is the first step of moving the development scheduling page into the admin page.
  - Admin > Timetable shows one room's classes for one week (Monday to Sunday) as a calendar, with the room picked from a drop-down. Saturday and Sunday are greyed.
  - Below the calendar, a green **Schedule Class** button opens `/admin/schedule` in a new tab.
  - For now that page only shows a dialog saying it is under development.
  - White interface with Google colours.
- **User decisions:**
  - Only the Timetable tab was to be changed. The user approved touching `router.js`, `App.vue`, `backend/app/main.py` and the existing routing tests for the new page.
  - The calendar **replaces** the Timetable tab's old date-range list. Its Edit (reschedule) and Remove (cancelled class) buttons are gone from the page. The `PUT` and `DELETE /api/admin/timetable/{id}` endpoints and their database functions are unchanged.
- **Implemented:**
  - `frontend/src/admin/RoomTimetable.vue` (calendar) and `roomCalendar.js` (pure helpers).
  - Calendar data:
    - It uses the existing `GET /api/admin/timetable/rooms` and `GET /api/admin/timetable` for the whole campus week (Monday 00:00 to Monday 00:00, `+08:00`), filtered by the selected room in the browser.
    - Times are shown in `Asia/Kuala_Lumpur`.
    - Overlapping classes sit side by side. Cancelled classes are grey and struck through; rescheduled classes show "Moved".
    - The hour range is 8 AM–7 PM and grows for earlier or later bookings.
    - Demo mode uses the page's demo data.
  - `AdminPage.vue`: the Timetable tab renders the calendar. The old list, its state and its edit/remove functions were removed.
  - `SchedulePage.vue`: placeholder dialog.
  - `router.js` and `App.vue`: `/admin/schedule` is an admin page.
  - `main.py`: serves `/admin/schedule` with the same login and role redirects as `/admin`.
- **No API or database change.** Meetings are not shown, because the admin timetable API returns classes only.
- **Verification:**
  - New `roomCalendar.test.js`: 7 tests pass (weeks, weekend, campus time zone, room filter, hour range, overlap lanes, labels).
  - Login/routing 7/7 and lecturer 12/12 frontend tests pass; `npm run build` succeeds.
  - Backend `test_auth.py` and `test_app.py`: 42 passed, 1 skipped, including new `/admin/schedule` page and redirect checks.
  - Visual check in headless Edge against a temporary local server with synthetic data and a fake admin session (no Supabase), at 1280 px and 390 px. On a phone the calendar scrolls sideways inside its card, and the page itself does not. Not checked against hosted Supabase.

## `/admin/schedule` scheduling workspace and multi-intake API — 12 November 2026

- Work done on branch `feature-admin-room-timetable`, continuing the previous entry.
- **Requirement:** move the development scheduling page's features into `/admin/schedule`, using intake names instead of typed UUIDs.
  - A left panel and a right panel, with an adjustable width.
  - The left panel lists the database's intakes with checkboxes.
  - A green **Generate Preview** button at the top right. After a preview it becomes **Regenerate Preview**, and a blue **Schedule with preview** button appears to its right.
  - The right panel turns the API response into a readable preview.
  - Saving needs a double confirmation that says it cannot be undone and is published to everyone.
- **Decision (user, 12 November 2026):** extend the API rather than send one request per intake. Separate per-intake previews could double-book a shared lecturer, room or student, and the second save would be refused as stale.
- **Backend:**
  - `preview.py`: `GenerationRequest` accepts `intake_ids` (1–100) as an alternative to `intake_id`; exactly one must be given, and `group_number` is only allowed with `intake_id`.
  - `select_scope` filters by a set of intakes. One intake keeps the original revision; several use a version-2 revision over the sorted IDs.
  - Responses add `intake_ids`, `scope = "intakes"` and a nullable `intake_id`, plus a new `unplaced` list naming classes that cannot be placed (course, intake, group, reasons).
  - `save.py`: `SaveResult` adds `intake_ids`.
  - The development test page is unchanged and still works. Contract: [preview API](schedule-preview-api.md).
- **Frontend** (`frontend/src/admin/`):
  - `SchedulePage.vue`: page, actions, generate/confirm flow, and a resizable split. The divider can be dragged, moved with the arrow keys (Home/End), or reset by double-click; its width is remembered in `localStorage`. Panels stack on narrow screens.
  - `IntakePanel.vue`: week navigation, a date jump, search, Select all/Clear, and intake checkboxes.
  - `PreviewPanel.vue`:
    - the outcome in plain language, plus summary figures;
    - "Show" by intake, room or lecturer;
    - calendar and list views;
    - the unplaced classes and their reasons, or the diagnostics;
    - generating progress with a timer, and an outdated-selection warning.
  - `ScheduleConfirmDialog.vue`: summary, the irreversible/published-to-everyone warning, a required tick box, then **Confirm and schedule**.
  - `scheduleApi.js` (fetch and errors, 401 → login) and `schedulePreview.js` (pure helpers).
  - `WeekGrid.vue`: the Monday–Sunday grid, now shared with the room timetable (which was refactored to use it).
- **Behaviour:**
  - **Schedule with preview** is disabled while the week or intake selection differs from the preview, for an incomplete preview, or after a failed save other than "busy".
  - After saving, the page shows "Scheduled: N classes are now live" and offers **Generate Preview** again.
  - Leaving with an unsaved complete preview asks the browser for confirmation.
  - Previews are still not stored.
  - Generation can take about two minutes.
  - On Vercel the scheduling API is blocked (development-only), and the page shows that advice. **Superseded the same day:** the API now works on Vercel (see "Scheduling in production" below).
- **Verification:**
  - Backend preview/save tests: 82 passed and 2 failed. The 2 failures are the known older preview tests; new tests cover multi-intake joint scheduling, labelled unplaced classes, validation and a multi-intake save.
  - Full backend suite: 347 passed, 10 failed, 1 skipped. These are the same 10 older loader/preview failures as before this work.
  - Frontend: `schedulePreview.test.js` 8/8, `roomCalendar.test.js` 7/7, login 7/7, lecturer 12/12; `npm run build` succeeds.
  - The development page's tests: 20/20, including the two served-page tests against the synthetic QA service.
  - Walkthrough in headless Edge against the real backend and solver on synthetic data (temporary scratchpad QA server with extra synthetic intakes; no Supabase):
    - three intakes, 7 of 7 classes placed (`OPTIMAL`, about 45 s);
    - button changes, the outdated warning and the double confirmation;
    - a save;
    - divider drag and keyboard;
    - 1440 px and 390 px widths.
  - The first walkthrough found that quick successive checkbox clicks were lost (the panel updated from a stale copy). Fixed: the page now owns the selection, and the panel sends toggle/add/clear events.
  - Not checked against hosted Supabase.

## Admin class rescheduling — 12 November 2026

- Work done on branch `feature-admin-room-timetable`.
- **Requirement:**
  - Admin > Timetable gets a blue **Reschedule** button beside **Schedule Class**. A class can be selected in the calendar; double-clicking it, or the button, opens a dialog.
  - The dialog shows the class (with its ID in a drop-down at the top) and its venue, time, type, intake, group and lecturer.
  - Venue and time can be changed. Venues not available at the chosen time are greyed out, and the backend is asked again whenever the time changes.
  - A time at which the chosen venue is not free cannot be picked.
  - Cancel and Save both ask again when something changed: Cancel says changes are lost; Save says the change is published to everyone involved.
  - The user allowed backend changes and asked for the new API to be documented.
- **Backend:**
  - New `backend/app/scheduling/reschedule.py`:
    - `GET /api/admin/timetable/{id}/availability` and `POST /api/admin/timetable/{id}/reschedule`, registered in `main.py`.
    - Both use the target week's snapshot, with the class as the only class to place and its own booking removed, through `BookingValidator` and `CandidateGenerator`, so every compulsory rule applies (including the gap and opening hours). Moves into other weeks and classes without a teaching occurrence work.
    - The save re-checks the move, then calls `admin_reschedule_class` with the admin's token, which does the lock, re-check, `rescheduled` status and audit row in one transaction.
  - `observability.py` traces the two new paths (by pattern; the class ID is not logged).
  - Full contract: [admin rescheduling API](admin-reschedule-api.md).
- **Frontend:**
  - `RescheduleClassDialog.vue`:
    - a class drop-down (this week's upcoming active classes) with the class ID;
    - the class details;
    - Monday–Friday day buttons with week arrows (past days disabled);
    - a 15-minute start-time grid: chosen, current and blocked states, click again to clear;
    - a venue drop-down with greyed-out options and short reasons;
    - a required reason;
    - an inline discard or publish confirmation.
  - `reschedule.js`: pure helpers and their tests.
  - `RoomTimetable.vue`: click to select (blue outline), double-click or Enter to open, the blue Reschedule button, a success message, and a reload after a move.
  - `WeekGrid.vue`: the selection and open events.
  - `scheduleApi.js`: `getAvailability` and `rescheduleClass`. The re-login redirect now returns to the current page.
- **Design decisions:**
  - A reason is required, because `admin_reschedule_class` needs one for the change history. **Superseded the same day:** the reason is optional (see the next entry).
  - Only classes that have not started can be moved, matching the lecturer page.
  - Choosing a new day clears the time, so a room that is busy at the old time can still be chosen. This avoids being stuck when neither the new time nor the new room is free with the other.
  - Reschedule is disabled with demo data.
- **Verification:**
  - New `test_admin_reschedule.py`: 28 passed. Full backend suite: 375 passed, 10 failed, 1 skipped (the same 10 older loader/preview failures).
  - `reschedule.test.js` 5/5, `schedulePreview.test.js` 8/8, `roomCalendar.test.js` 7/7; `npm run build` succeeds.
  - Walkthrough in headless Edge against the real backend on synthetic data, with a fake database function that applies the move (no Supabase). It covered select, double-click, a blocked time not selectable, the next week, room greying, publishing with confirmation (the calendar updated), Cancel with Keep editing / Discard, and 1280 px and 390 px widths.
  - The first run of the walkthrough failed on a QA-server bug (the fake session did not set the access token, so the save correctly returned 401 and redirected to login). The app needed no change.
  - Not run against hosted Supabase. The save needs migrations 202611110001 and 202611120003 applied.

## CS(CYB) course seed, years 1 to 3 — 12 November 2026

- **Requirement:** course and intake data for the CS(CYB) cohort, matching the user's own intake. Years 1 and 2 come from the user's transcripts and Year 3 from the `APD3F2609CS(CYB)` programme schedule. Internship is excluded. No personal or grade data was copied.
- **Added:** [supabase/seed_courses_cyb.sql](../../supabase/seed_courses_cyb.sql), with 41 modules for `APD1F2407CS(CYB)` (15), `APD2F2506CS(CYB)` (14) and `APD3F2609CS(CYB)` (12). That is 82 course rows, 82 offerings, and sections for every group (164 with 2 groups). All components are 120 minutes, each module has one lecturer from `LEC004`–`LEC020`, and no teaching plans or sessions are created. It works with or without the removed `required_room_type` column.
- **Course codes (changed the same day at the user's request):** `CS101-*` for Year 1, `CS201-*` for Year 2 and `CS301-*` for Year 3. At the user's request, IN and PYP are not created by this seed. Year 1 links the original `CS101-IN`/`CS101-PYP` courses from `seed_courses.sql` without changing them, so that seed must run first; otherwise this one stops and changes nothing. It creates 78 course rows. Now 53 checks pass, with `seed_courses.sql` run first in both scenarios.
- **Revert script (same day, user request):** [supabase/revert_courses_cyb.sql](../../supabase/revert_courses_cyb.sql) deletes the cohort's sections, offerings and 78 course rows. It keeps `seed_courses.sql` rows, the intakes and memberships, and any course another intake uses. It stops without deleting if a class session or teaching plan uses a cohort section. With it, the test passes 75 checks. Not run on hosted Supabase.
- **Teaching plans (same day, user request):**
  - Scripts: [supabase/seed_teaching_plans_cyb.sql](../../supabase/seed_teaching_plans_cyb.sql) and [supabase/remove_teaching_plans_cyb.sql](../../supabase/remove_teaching_plans_cyb.sql).
  - User choices: all three intakes in the same weeks, 14 consecutive weeks, 1 lesson a week. The start Monday is the assistant's default, 16 Nov 2026. That gives 164 plans and 2,296 lessons, with no times or rooms.
  - **Known infeasibility, accepted by the user:** the same 80 sample students are in all three intakes, so each would need 164 h a week. Generate Preview cannot place them all.
  - Removal switches off the lesson delete protection only inside its own transaction. It stops if a class session is linked to a lesson. Remove the plans before reverting the courses.
  - 27 new checks passed on the fully migrated schema; related suites still pass. Not run on hosted Supabase.
  - **Reduced on 13 November 2026** at the user's request ("too much for sample data"); this supersedes the 164-plan version above:
    - The user chose a small set that can be scheduled: three Semester 1 modules per intake (`CS301-INV/ALG/VAPT`, `CS201-ENTINV/OODJ/SDM`, `CS101-IDB/IN/PYP`), with nine different lecturers. That gives 36 plans and 504 lessons.
    - The plan script stops if other CS(CYB) modules still have plans. The removal script still covers all 41 modules, so it also clears the old version.
    - Real solver on a synthetic copy of the week (same 80 students, `seed_rooms.sql` rooms, configured settings): OPTIMAL, 36/36 placed in 91 s, no idle time. The plan test now passes 33 checks. Not run on hosted Supabase.
  - Details: [CS(CYB) course seed](cyb-course-seed.md#teaching-plans).
- **Removing other sample students (13 November 2026, user request):**
  - [supabase/remove_students_except_cyb_se.sql](../../supabase/remove_students_except_cyb_se.sql) keeps only the students of the three CS(CYB) intakes and `APU1F2611CS(SE)` (confirmed instead of the `APD1F2611CS(SE)` first written).
  - On the sample data it removes 880 students and 1,200 memberships, leaving 120.
  - It stops if a kept intake is missing, or if a student to be removed has a login link.
  - Undo by rerunning `seed_students.sql`.
  - 20 checks passed locally; not run on hosted Supabase. Details: [CS(CYB) course seed](cyb-course-seed.md#removing-the-other-sample-students).
- **Hosted state after the user's run and intake rename (13 November 2026):**
  - The user ran the scripts on hosted Supabase, renamed the CYB intakes and removed the other intakes.
  - Read-only queries confirmed four intakes: `APD1F2611CS(CYB)` (was `APD1F2407CS(CYB)`), `APD2F2611CS(CYB)` (was `APD2F2506CS(CYB)`), `APD3F2611CS(CYB)` (was `APD3F2609CS(CYB)`) and `APU1F2611CS(SE)`.
  - Students: 121 (one without an intake) with 280 memberships.
  - Courses: 85, including a stray test course `ur mom` with no offering. 88 offerings.
  - Plans: 42, of which 36 are CS(CYB) and 6 SE. Class sessions: 8, all SE.
  - **The CS(CYB) scripts and `seed_students.sql` still use the old codes.** Do not rerun `seed_courses_cyb.sql` or `seed_students.sql`. The other scripts stop or do nothing until their codes are updated.
  - Documentation only; no data changed. Table: [hosted state](cyb-course-seed.md#hosted-database-state--13-november-2026).
- **Separate Year 2 and Year 3 students (13 November 2026, user request):**
  - Problem: the renamed CS(CYB) intakes still shared the same 80 sample students.
  - [supabase/split_cyb_students.sql](../../supabase/split_cyb_students.sql) removes all current members from `APD2F2611CS(CYB)` and `APD3F2611CS(CYB)`; they stay in Year 1.
  - It adds 80 new single-intake students to each: `TP001001`–`TP001080` and `TP001081`–`TP001160`, 40 per group, with new surnames so no name repeats.
  - Hosted codes, names and the affected students were checked read-only first.
  - 19 checks passed locally; to be run by the user. Details: [CS(CYB) course seed](cyb-course-seed.md#separate-students-for-years-2-and-3--13-november-2026).
- **Assumptions to confirm:** Year 3 module abbreviations are made up. Year 1/2 lecture+lab versus lecture+tutorial is inferred. Both Year 3 electives are included. Semesters are not stored. Details and the Year 3 teaching weeks: [CS(CYB) course seed](cyb-course-seed.md).
- **Verification:** new `supabase/tests/courses-cyb.test.cjs` passed 39 checks on PGlite, run on both the legacy schema and the schema without the room column. `courses.test.cjs` still passes 20. Not run on hosted Supabase.

## Scheduling in production, optional reschedule reason, lecturer re-check — 12 November 2026

- Work done on branch `feature-admin-room-timetable`, after committing the admin rescheduling work and merging `main` (PRs #18 and #20).
- **Requirements (user):**
  - "The generate preview and saving feature seems keep relying on the local environment… The feature now should be migrated to be usable on production environment."
  - The reschedule reason stays in the dialog but becomes optional; the API accepts a request with or without it.
  - Check whether the rescheduling feature misses any values.
  - Only classes that have not started can be moved (confirmed). Choosing a new day clears the time (confirmed as the user's preference).
  - Validate the teammate's lecturer rescheduling fixes.
- **Scheduling in production:**
  - Cause: generate and save shared the test page's local-only guard, and Vercel's forwarded headers always triggered `403 LOCAL_ACCESS_ONLY`. Nothing else depended on the local machine (no server-side preview state).
  - Change: the API now needs an admin login and a same-site `Origin` (`origin_allowed()` in `preview.py`, also used by the reschedule `POST`). The test page under `/admin/development/` keeps all its local-only checks. The frontend's local-only messages were replaced, and a platform `504` now shows `SERVER_TIMEOUT` advice.
  - Vercel limits checked: 300 s default duration (Fluid compute) against the 120 s solver limit; about 180 MB of packages against the 250 MB limit. Details, and the save race between instances: [Vercel deployment](vercel-deployment.md#scheduling-on-vercel-since-12-november-2026).
  - `AGENTS.md` scheduling rule updated: the API is no longer local-only; the test page still is.
- **Optional reason:** `reason` may be missing, `null` or blank; the API then records `"No reason given"`, because `admin_reschedule_class` requires a non-empty reason. That avoids a new migration. The dialog label now says "optional", and Save no longer waits for a reason.
- **Values added to the dialog:**
  - students in the group, from a new `student_count` field in the availability response (the seats a room needs);
  - the class length, such as "1h 30m";
  - the current venue's seats;
  - status: "As scheduled", or "Rescheduled before" (from the new `status` field, which is also on the calendar data).
  - Considered and not added: the teaching week or occurrence (not meaningful to an admin), the change history (would need a new read), and notifications (no notification system exists; people see changes in their timetables).
- **Lecturer re-check:** read the merged `lecturer.py` and the lecturer page, and ran the existing tests. Findings 2, 5, 6, 8, 10, 12 and 13 are fixed. Findings 1 and 3 are only partly fixed: the opening time is 08:00 instead of 08:30, and the room table differs from the configured policy. Findings 4, 7 and 9 are open, and the review's intake-code/group-size fix was lost in commit `00e0a83`. Table: [review](lecturer-reschedule-review.md#re-check-after-the-lecturer-page-update-12-november-2026). No lecturer code was changed.
- **Verification:**
  - `test_admin_reschedule.py`: 33 passed (new: the optional reason in four forms, the Origin check behind a proxy, and `student_count`/`status`).
  - `test_schedule_preview.py` and `test_schedule_save.py`: the access tests were rewritten. The API now works in production mode, from a remote client and behind proxy headers; another site's `Origin` is refused before the database; and the test page stays local-only. 86 passed, 2 failed (both among the 10 older failures; they also fail without this change).
  - Full backend suite: 382 passed, 12 failed, 1 skipped. That is the same 10 older loader/preview failures, plus 2 lecturer tests in `test_auth.py` that fail on `main` after PR #18 (`test_lecturer_timetable_shows_the_real_intake_code_and_group_size`, and `test_admin_can_read_any_record_and_reschedule_on_behalf` with `KeyError: 'course_type'`). Both also fail without this change.
  - Frontend: `reschedule.test.js` 6/6, `schedulePreview.test.js` 8/8 (new: a platform `504` gives `SERVER_TIMEOUT`), `roomCalendar.test.js` 7/7, `auth.test.js` 7/7, `lecturer.test.js` 30/30; `npm run build` succeeds.
  - Headless Edge walkthrough on synthetic data, with no reason entered: Save was enabled, the fake database function received `"No reason given"`, and the dialog showed the group size, length, seats and status.
  - Not verified on the live Vercel site or hosted Supabase.

## Lecturer rescheduling fix — 12 November 2026

- Work done on branch `feature-admin-room-timetable`, after committing the production-scheduling work (`8dce393`).
- **Requirement (user):** "plan and implement the fix on lecturer. Ensure only fix the 5 area you brief to me": the opening time, the room rules, locking, error text, and the lost real intake code and group size.
- **Plan:** reuse the scheduling engine for checks (the AGENTS.md rule that every move follows the shared validator), and move the write into a database function, as the admin dialog already does. Keep the lecturer API's URLs and response shapes, so the page needs no API change.
- **Backend:**
  - `lecturer.py`: the move and the suggestions use `scheduling/reschedule.py` (`load_roster`, `load_target_snapshot`, `explain`, `start_grid`, `free_room_ids`, `run_move_function`). The hard-coded hours, room table, gap and asyncio lock were removed. Reads use the safe shared client from `student.py`, and all errors go through `safe_database_error`. `group_facts` was restored. The router now receives the full settings (`main.py`).
  - `scheduling/reschedule.py`: those helpers moved to module level; the admin endpoints use them unchanged. `run_move_function` maps database error codes to fixed messages for both callers.
  - New migration `202611120004_lecturer_reschedule.sql`: the shared `campus_private.move_class_session`, `admin_reschedule_class` calling it, and the new `lecturer_reschedule_class` with an ownership check. Explained in the [migration guide](hosted-migrations.md); the status query has a new column.
- **Frontend (lecturer page, opening time only):** `time.js` opens at 08:30, the dialog hint says 08:30, and the demo data uses 08:30 and the configured room table.
- **Details, before and after:** [fix](lecturer-reschedule-review.md#fix-12-november-2026).
- **Verification:**
  - New `test_lecturer_reschedule.py`: 22 passed. It covers:
    - a move as one function call with the user's token;
    - the optional reason;
    - an admin acting for a lecturer;
    - 08:00, 08:29 and a too-late end refused, and 08:30 accepted;
    - a weekend;
    - the lab, auditorium and small rooms;
    - room, gap, lecturer and student clashes;
    - another lecturer's class;
    - safe database errors;
    - suggestions that start at 08:30, use suitable rooms only and offer nothing at a weekend.
  - `test_auth.py`: 26 passed. The intake-code/group-size regression test passes again, and the on-behalf test now checks that no direct writes are made.
  - `test_admin_reschedule.py`: 33 passed after the refactor.
  - PGlite: the new `lecturer-reschedule.test.cjs` passed 14 checks: owner only, history by the lecturer, stale and clash refusals, the admin path, and the internal routine not being callable. `admin-reschedule-fixes.test.cjs` (24) and `admin_timetable.test.cjs` still pass. The status query reported correctly before and after 003 and 004.
  - Frontend: `lecturer.test.js` 30/30, after updating three tests that encoded 08:00 and "labs only a lab".
  - Full backend suite: 406 passed, 10 failed, 1 skipped. Only the 10 older loader/preview failures remain; the two lecturer failures from `main` are fixed. Other PGlite suites still pass (`rescheduled-status` 33, `save-audit` 46). Frontend unit tests all pass and `npm run build` succeeds.
  - Not run against hosted Supabase or on Vercel; the lecturer page was not opened in a browser.

## Scheduling time limit of 5 minutes — 13 November 2026

- **Requirement (user):** "expand the configuration to let the system allows up to 5 minute on scheduling".
- **Decision (user, 13 November 2026):** the **whole** scheduling request should take at most 5 minutes, on any Vercel plan. The alternative was a 300 s search plus `maxDuration` 360 s in `vercel.json`, which needs Vercel Pro (Hobby is capped at 300 s).
- **Change:**
  - `Config/config.json` `scheduling.solver.max_time_seconds` is now **280** (was 120). That leaves about 20 s of Vercel's 300 s function limit for loading the week, building the model and checking the result.
  - `/admin/schedule` now says a preview "can take up to about five minutes".
  - The docs were updated: timetable quality, preview API, CP-SAT, README and [Vercel deployment](vercel-deployment.md#scheduling-on-vercel-since-12-november-2026).
  - `vercel.json` is unchanged.
- **Effect:**
  - With preferences on, a preview usually runs for the whole limit. It now waits up to about 4 min 40 s for the search, and holds the one-at-a-time slot (`GENERATION_BUSY`) for that long.
  - Saving is not affected; it does not run the solver.
- **Limits:**
  - If loading the week from Supabase takes longer than about 20 s, Vercel stops the request at 300 s. The page then shows the `SERVER_TIMEOUT` message.
  - Vercel notes that idle HTTP/1.1 connections may be closed by network layers during long requests. Not checked on the live site.
- **Verification:** the configuration loads with the new value (`load_settings()`), and the preview tests pass. Not run on Vercel.

## Scheduling time limit set to 1 minute — 13 November 2026

- **Requirement (user):** "change back the config time for scheduling to 1 minutes", on a new branch (`scheduling-time-limit-1-minute`).
- **Change:**
  - `Config/config.json` `scheduling.solver.max_time_seconds` is now **60** (was 280 from the entry above).
  - `/admin/schedule` now says a preview "can take a minute or a little longer".
  - `test_solver.py` expects 60. The docs were updated: timetable quality, preview API, CP-SAT, README and Vercel deployment.
  - `vercel.json` is unchanged.
- **Effect:**
  - A preview's search stops after 60 s, then loading and checking are added. It holds the one-at-a-time slot (`GENERATION_BUSY`) for about that long.
  - With less search time, a week that needs a long search may end with `UNKNOWN` (no timetable found yet), or with a valid but less polished timetable (more idle time). Compulsory rules are unchanged. For comparison, the synthetic CS(CYB) week reached OPTIMAL in 91 s; under 60 s it would stop with the best timetable found so far, if any.
- **Verification:** `load_settings()` returns 60; `test_solver.py` 29 passed; preview page tests 9/9. Not run on Vercel or against hosted Supabase.

## Pause button for scheduling — 13 November 2026

- **Requirement (user):** "add a pause button on the scheduling page, which should stop the current scheduling work". Branch `scheduling-time-limit-1-minute`.
- **Decision:** a stopped CP-SAT search cannot be resumed, so **Pause stops the search and keeps what it has**: the best complete, valid timetable found so far, or none. Generating again starts a new search. The button is labelled Pause as asked; the page text says what it does.
- **Change:**
  - `solver.py`: `StopSignal` (thread-safe; calls CP-SAT `stop_search()` on the running search). `solve_weekly_schedule(..., stop=)` returns `FEASIBLE` with `stopped=True` and a `STOPPED` diagnostic when a valid timetable was found, `UNKNOWN` with `stopped=True` otherwise. A proven `OPTIMAL`/`INFEASIBLE` result is still reported as such. New `ScheduleResult.stopped` field.
  - `preview.py`: optional `run_id` on generate; new `POST /api/schedules/generate/stop` (admin, same-site, only the admin who started the run). While solving, a watcher checks every 0.5 s for a stop request or a disconnected caller and repeats the stop (CP-SAT can miss a stop sent just as a search starts).
  - `/admin/schedule`: an amber **Pause** button beside Generate while a preview runs. Pause calls the stop endpoint and waits for the answer (up to 15 s), or, when the stop is not accepted (for example another Vercel instance), stops waiting at once. A paused run with a timetable can be scheduled as usual; a paused run without one keeps the previous preview and says so.
  - Logging: the `solver_completed` event has `stopped`; new `generation_stop_requested` event; the stop path is traced.
  - Docs: [preview API](schedule-preview-api.md) (Pause section and `stopped` field), [timetable quality](timetable-quality.md) (preview time), README.
- **Limits:**
  - The stop reaches only the server process running the preview. On Vercel a stop request may land on another instance; the page then stops waiting, and the search stops only if the platform passes the closed connection on to the function. Not checked on Vercel.
  - Time spent loading the week from Supabase is not interrupted; the stop takes effect when the search starts (straight away).
- **Verification:**
  - Backend: 7 new solver/endpoint tests and 3 validation cases. A real CP-SAT search with a 30 s limit (a hard "market split" model) stopped about 0.5 s after Pause. Pause during improvement keeps the first valid timetable. Only the same admin can pause; logged-out 401, lecturer 403, wrong origin 403, bad bodies 422. `test_solver.py` + `test_schedule_preview.py`: 93 passed, with the same 2 failures as before this change (provider 401 code, timeout/missing config).
  - Frontend: 25/25 admin page tests (3 new for Pause); build succeeds.
  - Headless Edge against the real backend on synthetic data, with a solver that waits for Pause. Checked: Pause shown while generating; paused with no timetable; paused with a timetable kept and Schedule enabled; a refused stop (page stops waiting, and the server stopped its search about 1.5 s later because the connection closed); next Generate runs at once; phone layout. Not run against hosted Supabase or Vercel.

## Admin page clean-up, intake students and intake charts — 12 November 2026

- **Requirement (user, 12 November 2026)** for the `/admin` page:
  1. Remove the "Main menu" link. It had already been removed on `main`; the leftover `<title>SClass · Main menu</title>` in `frontend/index.html` is now `SClass`.
  2. Remove the access-token banner, including "Connect" and "Try local demo". The page now uses only the admin's login cookie and loads on open. The backend still accepts a pasted Bearer token, which the page no longer sends.
  3. Remove the course type from the Courses page.
  4. Remove the Students tab. Students are now reached only from Intakes > **Students**.
  5. Show charts and figures for the intakes: students and groups.
- **Decisions and reasons:**
  - **Course type kept in the database.** It is still required (`courses.course_type`, unique with `course_code`) and drives the scheduler's room policy. `Course.course_type` is now optional in the API: a new course without it is saved as `lecture`, and an edit without it keeps the stored type. Limitation: from the page, a second row with the same code (for example a CS101 lab next to the CS101 lecture) cannot be created, because it would default to `lecture` and clash with the unique key.
  - **Students are managed per intake** because a student's group belongs to the student–intake membership (`student_intakes`), not to the student.
- **Backend** (`backend/app/admin.py`); all routes are admin-only, like the rest of `/api/admin`:
  - `GET /api/admin/intakes/{id}/students`: the intake's students with `group_number`. The account link (`auth_user_id`) is not returned.
  - `POST /api/admin/intakes/{id}/students` with `{student_code, full_name, age?, group_number}`.
    - A code that already exists links that student as they are; their name and age are not changed, and the reply says `existing: true`.
    - Otherwise the request creates the student, then the membership. These are two writes, not one transaction: if the membership is refused (for example a group above `max_group`), the new student row is deleted again.
  - `PUT /api/admin/intakes/{id}/students/{student_id}`: updates code, name and age, then the group.
  - `DELETE /api/admin/intakes/{id}/students/{student_id}`: removes the membership. The student record is deleted as well only when the student is in no other intake and has no linked login. If something else (such as a meeting) still uses it, the record is kept and the reply says `student_deleted: false`.
  - `GET /api/admin/intakes` now embeds `student_intakes(student_id, group_number)` and `course_offerings(id)` so the page can count students, groups and courses. The group-number check failure (`23514`) now returns 422 with a readable message.
- **Frontend** (`frontend/src/admin/`):
  - `AdminPage.vue`: tabs Courses, Lecturers, Intakes, Timetable. Demo data was removed. A 401 sends the admin to `/login?next=/admin`.
  - `IntakesView.vue`:
    - figures: intakes, distinct students, groups, and the average students per group (over groups that have students);
    - a "Students per intake" bar chart whose hover/focus tooltip shows the split by group;
    - add, edit and delete intakes;
    - a **Students** button for each intake.
  - `IntakeStudents.vue`:
    - figures: students, groups, largest and smallest group;
    - a "Students per group" chart that includes empty groups;
    - group filter and search;
    - add, edit and remove students.
  - `BarList.vue` draws the single-series bar chart. `adminApi.js` handles requests; `intakeStats.js` holds the pure counting helpers.
  - `RoomTimetable.vue` is unchanged; its token and demo props now stay at their defaults.
- **Verification:**
  - New `backend/tests/test_admin_intake_students.py`: 7 passed. Together with `test_admin_timetable.py`: 8 passed.
  - Full backend suite: 241 passed, 2 failed, 122 skipped. The 2 failures (`test_auth.py::test_admin_can_read_any_record_and_reschedule_on_behalf`, `::test_lecturer_timetable_shows_the_real_intake_code_and_group_size`) fail the same way on unmodified `main`.
  - Frontend: `node --test src/admin/*.test.js` 17/17, including the new `intakeStats.test.js`; `vite build` succeeds.
  - Headless Edge walkthrough of the built page against a scratchpad mock API with synthetic data (no Supabase):
    - Courses, Intakes (with a tooltip shown) and an intake's Students view;
    - 1280 px and 390 px widths, with no horizontal scrolling and no console errors.
  - Not checked against hosted Supabase. That includes the PostgREST embeds (`students(*)` from `student_intakes`, and `student_intakes`/`course_offerings` from `intakes`), which rely on the existing foreign keys.

## Admin search and logins for new students and lecturers — 13 November 2026

- **Requirement (user, 13 November 2026):**
  1. Search for Intakes, Courses and Lecturers on the admin page.
  2. An email field on Add student and Add lecturer. Creating the user also creates a temporary password: their TP number plus 4 random digits. Follow Supabase's documentation on password encryption and authentication.
- **Decisions and reasons:**
  - **Search is in the browser.** The lists are already fully loaded, so filtering them needs no new API. It is case-insensitive, and every typed word must appear. Courses match code, name or linked intake codes; lecturers match code or name; intakes match the intake code.
  - **The TP number is the record's code** (`student_code`, `lecturer_code`).
  - **Supabase Auth hashes the password (bcrypt, per-password salt); the backend does not.** It creates the login with the Auth admin API and the server-only key, sends the password once over HTTPS, returns it once to the admin, and never stores or logs it. The sources and how each is applied are in [admin-created logins](admin-accounts.md).
  - **An existing student code still only links the existing student.** No login is created and the email is ignored, so an existing login is never replaced.
  - **An email that already has a login is refused (409), not linked,** so the page cannot take over another account.
  - This changes login decision 2 for these two forms; [login](login.md) is updated. Sign-up and password reset stay out of scope. (A forced password change at first login was added later the same day; see the next entry.)
- **Backend** (`backend/app/admin.py`):
  - `POST /api/admin/intakes/{id}/students` accepts `email` (required for a new code). For a new code it creates the login, then the student with `auth_user_id`, then the membership.
  - New `POST /api/admin/lecturers` (before the generic route) requires `email`, checks the code first, then creates the login and the lecturer row.
  - On failure, earlier steps are undone in reverse order, including deleting the new login. Supabase Auth errors are mapped to 409/422/502 with readable messages.
  - Replies with a password carry `Cache-Control: no-store`.
- **Frontend** (`frontend/src/admin/`):
  - New `search.js` (`matchesSearch`, `looksLikeEmail`) with `search.test.js`.
  - `AdminPage.vue`: a search box for Courses and Lecturers, cleared on tab change; an Email field on Add lecturer only (not on edit).
  - `IntakesView.vue`: a search box over the intake list. The chart and figures still cover all intakes.
  - `IntakeStudents.vue`: an Email field on Add student only, and a note that an existing code keeps its login.
  - New `NewLogin.vue`: the one-time "Login created" box with email, temporary password, **Copy** and **Done**.
- **Side effects** (details in [admin-created logins](admin-accounts.md)):
  - New students always have a login, so removing one from their last intake keeps the record.
  - Deleting a lecturer leaves their login unlinked; login refuses it.
- **Verification:**
  - `test_admin_intake_students.py`: 12 passed (5 new, 2 updated for the login steps).
  - Full backend suite: 246 passed, 2 failed, 122 skipped. The 2 failures are the same `test_auth.py` tests as in the previous entry (241 passed before; the 5 extra passes are the new tests).
  - Frontend: `node --test src/admin/*.test.js` 20/20 (3 new); `vite build` succeeds.
  - Not checked against hosted Supabase or in a browser, including the project's password rules and whether its `SUPABASE_KEY` may use the Auth admin API.

## Forced password change at first login — 13 November 2026

- **Requirement (user, 13 November 2026):** "When a new user logs into their interface require them to change their passwords." "New user" means an account created on the admin page with a temporary password (previous entry).
- **Decisions and reasons:**
  - **The flag is `app_metadata.must_change_password` in Supabase Auth,** set when the admin page creates the login. Users cannot change `app_metadata`, so they cannot skip the change, and no new table or migration is needed.
  - **Enforced by the backend, not only the page.** While the flag is set, every page goes to `/change-password` and every other API answers 403 `PASSWORD_CHANGE_REQUIRED`.
  - **The current password is asked for again** and checked by a fresh sign-in. This protects a left-open session, and the fresh session avoids Supabase's reauthentication requirement for password updates.
  - **Not a password reset:** forgot-password stays out of scope. This keeps login rule "do not change the student or lecturer page components": the app shell shows a separate page instead of them.
- **Backend:**
  - `auth.py`: `SessionUser.must_change_password` (from `app_metadata`), with `home` set to `/change-password` while it is true. Also `require_roles(..., allow_password_change=False)`, the new `POST /api/auth/change-password`, `SupabaseAuth.set_password` / `clear_password_flag`, and `logout(scope=...)`.
  - `main.py`: the `/change-password` page, and the role pages redirect while the flag is set. `admin.py` and `scheduling/preview.py`: the same block in their own session checks. `admin.py` sets the flag on create.
  - Details: [login: forced password change](login.md#forced-password-change).
- **Frontend:** `auth/ChangePasswordPage.vue` (current, new and confirm fields, show-passwords toggle, rules hint). `session.js` gains `changePassword` and `passwordProblem`, and `router.js` gains `PASSWORD_PAGE`. `App.vue` keeps a flagged user on that page and sends them to their home page after the change. The student and lecturer page components are unchanged.
- **Verification:**
  - New `backend/tests/test_password_change.py`: 4 passed, against a mock Supabase Auth. It covers:
    - the blocked APIs and pages;
    - wrong, same, short, too long and breached passwords;
    - the flag cleared and the old session revoked;
    - logging in with the new password, and not with the old one;
    - a failed flag update;
    - accounts without the flag.
  - `test_admin_intake_students.py` (create body now has `app_metadata`): 12 passed.
  - Full backend suite: 250 passed, 2 failed, 122 skipped. These are the same 2 `test_auth.py` failures as before.
  - Frontend: `node --test src/auth/auth.test.js src/admin/*.test.js` 30/30 (3 new); `vite build` succeeds.
  - After rebasing this work (with the two entries above) onto the updated `main` (branch `feature-admin-accounts`): full backend suite **312 passed, 0 failed, 132 skipped** (the 2 `test_auth.py` failures were fixed on `main`); frontend `src/auth/auth.test.js` + `src/admin/*.test.js` 40/40; `vite build` succeeds.
  - Not checked against hosted Supabase or in a browser.
