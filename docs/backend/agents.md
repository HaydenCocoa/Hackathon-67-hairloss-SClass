# Backend record

Last updated: 10 November 2026 (Asia/Kuala_Lumpur).

## Documentation convention

This is the main record for backend requirements, decisions, implemented changes, planned work, verification, and unresolved questions. Keep it updated whenever backend work changes. Put detailed notes in separate Markdown files in this directory and link them here. Clearly distinguish implemented behavior from proposals and plans.

The user requested this convention on 10 November 2026. Repository-level `AGENTS.md` records it for future work. The detailed development checklist remains in [task_hayden.md](../../task_hayden.md).

## Project direction

- Build the scheduling backend before the remaining frontend, notification, and AI features.
- Target one teaching week initially, with existing student groups, fixed lecturers, and one room per class.
- Prevent conflicts using actual student identities across all their intake memberships.
- Respect both class and meeting bookings and preserve future reservations.
- Generate a valid timetable before optimizing student gaps, lecturer gaps, and room utilization.
- Proposed algorithm: OR-Tools CP-SAT for generation involving many classes; simpler candidate search and ranking for one-class rescheduling. The solver is planned and is not installed or implemented yet.
- Separate generation previews from authorized, transactional booking commits.

Source: [Notes / Hackathon](https://app.notion.com/p/4117da63706d807095f2fbdab3321a17), last edited 9 November 2026. The lecturer use case includes cancelling or moving a class to a scheduled week or reserving a placement before a future week is generated.

## Accepted calendar decisions

- `Config/config.json` controls teaching weekdays and opening hours.
- Initial hours: Monday–Friday, 08:30–18:00, `Asia/Kuala_Lumpur`.
- A class may start at any time if its full duration fits inside opening hours. No fixed start-time grid, mandatory breaks, or travel buffer.
- Omitted weekdays are closed. Explicit closure dates override weekly hours; the initial closure list is empty.
- Timestamps must include timezone information. Calendar eligibility is separate from resource availability.

See [step 1: configurable teaching calendar](scheduling-calendar.md) for the configuration, rationale, code interface, behavior examples, affected files, and verification details.

## Current implementation

The existing backend provides health/configuration checks, a Supabase read-connectivity check, frontend serving, and student profile/timetable reads. These are existing components, not newly completed scheduling milestones. Authentication integration and trusted booking writes remain future work.

Step 1 now adds validated scheduling settings, a reusable calendar helper, and initialization on FastAPI app state. Invalid calendar settings fail startup. The helper accepts arbitrary start timestamps and checks the complete interval against configured local opening hours. It does not generate classes or check lecturer/student/room conflicts.

Step 2 adds database-defined weekly teaching plans, automatic expansion into stable occurrences, optional booking links, cancellation/move integrity, and an internal paginated weekly-demand reader. The migration is verified locally but not applied to a hosted project. See [implemented weekly teaching plans](weekly-teaching-plans.md) for setup, interfaces, decisions, and limits.

No database schema or hosted data was changed for step 1. No frontend change was needed.

## Development roadmap and status

| Step | Requirement and completion target | Status |
| --- | --- | --- |
| 1 | Configurable teaching calendar and reusable full-interval eligibility check | Complete; verified |
| 2 | Database-backed weekly teaching requirements and stable occurrences, with cancellation and replacement tracking | Core implementation verified locally; hosted migration pending; additional proposals under review |
| 3 | Use existing database scheduling inputs; defer meeting and impossible-arrangement fixtures for the initial MVP | Complete based on user confirmation; no new runtime code |
| 4 | Validated scheduling input snapshot resolving rosters, resources, requirements, and existing bookings | Complete and verified locally; snapshot migration pending for hosted use |
| 5 | Explainable room, lecturer, student, and reservation conflict validation | Complete and verified locally; no new migration |
| 6 | Feasible start ranges and suitable rooms without preset teaching slots | Complete and verified locally; no new migration |
| 7 | CP-SAT generation satisfying all mandatory constraints and reporting accurate solver status | Complete and verified locally; no new migration |
| 8 | Configurable objectives for student gaps, lecturer gaps, and room utilization | Planned |
| 9 | Generation preview API including assignments, quality, diagnostics, and input revision | Planned |
| 10 | Authorized, transactional commits with revalidation, concurrency control, audit, and retry protection | Planned |
| 11 | Safe rescheduling, cancellation, and fixed future reservations | Planned |
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

## Open items and limits

- No further user input is needed to finish step 1.
- No holiday dates have been supplied; `closed_dates` is empty and does not automatically import public holidays.
- Initial opening windows are same-day only; overnight opening is not implemented.
- Full availability, timetable generation, booking persistence, permissions, and concurrency protection are not completed by the calendar milestone.
- Later generation work must choose an explicit solver time precision without reintroducing preset teaching slots.

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
- Existing offering-end-date and system room-policy proposals are preserved as pending. This implementation retains `required_room_type`, does not enforce an offering end date, and does not introduce automatic holiday or break handling.
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

## Step 4 implementation — 10 November 2026

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
- Updated the checklist, root/database README, detailed loader notes, simulation evidence record, and room-removal compatibility notes. Step 4 is complete locally; apply the new snapshot migration before live use. Availability/conflict validation is step 5 and remains unimplemented.

## Step 5 implementation — 10 November 2026

- The user confirmed the room mapping: lectures may use classrooms or auditoriums; tutorials and labs may use classrooms or labs. Added `scheduling.room_compatibility` to tracked configuration. `others` starts with an empty mapping and is rejected until explicitly configured.
- Added typed configuration and immutable `RoomRule` values to the scheduling snapshot. Input fingerprints include the captured policy. Input loading remains one read-only RPC; no extra external request or migration is needed.
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
