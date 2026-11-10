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
| 4 | Validated scheduling input snapshot resolving rosters, resources, requirements, and existing bookings | Planned |
| 5 | Explainable room, lecturer, student, and reservation conflict validation | Planned |
| 6 | Feasible start ranges and suitable rooms without preset teaching slots | Planned |
| 7 | CP-SAT generation satisfying all mandatory constraints and reporting accurate solver status | Planned |
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
