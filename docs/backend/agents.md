# Backend record

Last updated: 12 November 2026 (Asia/Kuala_Lumpur).

## Documentation convention

This is the main record for backend requirements, decisions, implemented changes, planned work, verification, and unresolved questions. Keep it updated whenever backend work changes. Put detailed notes in separate Markdown files in this directory and link them here. Clearly distinguish implemented behavior from proposals and plans.

The user requested this convention on 10 November 2026. Repository-level `AGENTS.md` records it for future work. The detailed development checklist remains in [task_hayden.md](../../task_hayden.md).

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
- A class may start at any time if its full duration fits inside opening hours. No fixed start-time grid, mandatory breaks, or travel buffer.
- Omitted weekdays are closed. Explicit closure dates override weekly hours; the initial closure list is empty.
- Timestamps must include timezone information. Calendar eligibility is separate from resource availability.

See [step 1: configurable teaching calendar](scheduling-calendar.md) for the configuration, rationale, code interface, behavior examples, affected files, and verification details.

## Current implementation

The existing backend provides health/configuration checks, a Supabase read-connectivity check, frontend serving, and student profile/timetable reads. These are existing components, not newly completed scheduling milestones. Authentication integration and trusted booking writes remain future work.

Step 1 now adds validated scheduling settings, a reusable calendar helper, and initialization on FastAPI app state. Invalid calendar settings fail startup. The helper accepts arbitrary start timestamps and checks the complete interval against configured local opening hours. It does not generate classes or check lecturer/student/room conflicts.

Step 2 adds database-defined weekly teaching plans, automatic expansion into stable occurrences, optional booking links, cancellation/move integrity, and an internal paginated weekly-demand reader. It works with or without `class_sections.required_room_type`. The user confirmed Step 2 complete on 11 November 2026. The original design was verified locally on 10 November; this record holds no automated test results for the 11 November compatibility edit. See [implemented weekly teaching plans](weekly-teaching-plans.md) for setup, interfaces, decisions, and limits.

Steps 4-7 add the validated weekly snapshot, shared booking validator, unrestricted candidate ranges, and complete CP-SAT feasibility generation with post-solve verification. Step 8 quality optimization is postponed. Step 9 exposes read-only generation through a local-development HTTP API and a service-hosted test page; these are verified locally. Step 10 adds saving a reviewed preview to `class_sessions` through the same local-development API and page (see [timetable saving](timetable-saving.md)). Login with Supabase Auth and role-based access were added on 12 November ([login](login.md)), and the save audit followed the same day ([save audit](save-audit.md)); a database-transactional recheck-and-commit remains future work.

The step 4 loader was changed on 11 November at the user's direction: the backend now reads existing Supabase tables/views and assembles its own scheduling input. It no longer invokes the optional historical snapshot RPC migration. Verification of these direct reads is pending; see [the updated loader record](scheduling-data-loader.md). The separate PostgREST requests are not one transaction snapshot, so any later booking write must revalidate transactionally.

No database schema or hosted data was changed for step 1. No frontend change was needed.

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
| 9 | Selected-intake/group preview API and test page including assignments, diagnostics, and scope-bound input revision; quality deferred | Complete and verified locally; direct localhost/development access only |
| 10 | Authorized, transactional commits with revalidation, concurrency control, audit, and retry protection | Save implemented and verified locally on 11 Nov (recheck-then-single-insert). Admin login required since 12 Nov ([login](login.md)); save audit implemented 12 Nov ([save audit](save-audit.md)). Not run against hosted Supabase |
| 11 | Safe rescheduling, cancellation, and fixed future reservations | Planned. `rescheduled` booking status added 12 Nov ([details](rescheduled-status.md)); hosted SQL run pending |
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
- Step 7 uses integer microseconds without preset teaching slots. Quality optimization is postponed. Local preview generation and saving are implemented; login-based authorization, save auditing and a database-transactional commit remain open (step 10 follow-ups).

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
- **Time limit raised (12 November 2026):** at the user's request `scheduling.solver.max_time_seconds` is now 120 s (was 10 s). An unlimited value is not supported (0 and infinity are rejected at startup). With preferences on, a preview can take up to about 2 minutes plus loading time, holding the one-at-a-time slot.

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
