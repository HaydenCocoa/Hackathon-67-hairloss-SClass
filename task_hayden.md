# Hayden — Backend Class Scheduling Development Plan

## Goal

Build a backend that accepts a teaching week and its required classes, generates a complete, clash-free timetable, and allows the result to be reviewed and saved.

Complete the core scheduling workflow before building the remaining frontend, notifications, or AI features.

Source: [Notes / Hackathon](https://app.notion.com/p/4117da63706d807095f2fbdab3321a17), last edited 9 November 2026.

Backend decisions, implementation details, verification, and current status are recorded in [docs/backend/agents.md](docs/backend/agents.md).

## Initial scope

- Generate one teaching week at a time.
- Use fixed lecturers, existing student groups, and one room per class.
- Respect all student intake memberships when checking attendance conflicts.
- Respect existing classes, meetings, and reservations.
- Generate a valid timetable first; optimize timetable quality afterward.
- Support development and verification through the API without requiring a frontend.

## 1. Define the scheduling rules

- [x] Configure teaching weekdays and opening hours in `Config/config.json`: Monday–Friday, 08:30–18:00.
- [x] Accept any start time whose full class duration fits within opening hours; no fixed start-time interval.
- [x] Remove mandatory breaks and travel-time restrictions from the requirements, as requested on 10 November 2026.
- [x] Support explicit holiday/closure dates through `closed_dates`, initially empty.
- [x] Interpret the teaching calendar using `Asia/Kuala_Lumpur` and require timezone-aware booking timestamps. Persistence is implemented in a later step.
- [x] Define full availability as calendar eligibility plus the absence of conflicting classes, meetings, or reservations. Only calendar eligibility is implemented in step 1.
- [x] Keep personal availability preferences outside the initial scope unless explicitly added as input.
- [x] Validate calendar configuration at startup and initialize a reusable teaching-calendar helper.

Implementation and verification: [Teaching calendar](docs/backend/scheduling-calendar.md).

**Status:** complete on 10 November 2026. Backend verification: 43 passed, 1 optional simulation test skipped.

**Complete when:** calendar and availability rules are documented and configurable, and the engine can determine whether a proposed interval is inside the permitted teaching calendar.

## 2. Describe which classes must happen

**Status:** core weekly-recurrence requirements implemented locally on 10 November 2026; hosted migration is pending. See [implemented weekly teaching plans](docs/backend/weekly-teaching-plans.md) and the [original requirements discussion](docs/backend/teaching-requirements.md). Additional proposals below remain under review.

The offering-date proposal is deferred. Required-room-type removal is accepted; [a SQL-only patch is prepared and verified](docs/backend/required-room-type-removal.md), but hosted execution and backend/seed adaptation remain pending. See the [earlier design assessment](docs/backend/offering-end-dates-and-room-policy.md).

- [ ] Confirm the course-offering end date's inclusive local-date semantics, its relationship to teaching-plan bounds, and whether make-up classes require an explicit extension.
- [ ] Obtain real offering end dates and define a safe backfill/update policy; do not infer them from intake codes or silently invalidate existing bookings.
- [x] Prepare SQL for accepted `class_sections.required_room_type` removal, updating known views and trigger references; 25 local database checks passed.
- [ ] Apply the room-type removal patch to the hosted database and adapt backend readers, old course seeds/migrations, fresh setup, and the ERD.
- [x] Confirm and implement the system room policy for loading and validation: lectures use classrooms/auditoriums; tutorials and labs use classrooms/labs. Step 6 must reuse this captured policy for candidate generation.
- [ ] Keep automatic public-holiday and semester-break handling deferred; continue respecting configured hours and explicit closures.

- [x] Maintain recurring teaching plans in the database, as confirmed by the user.
- [x] Resolve teaching weeks from each section's first Monday and week count; starts can differ across sections/intakes.
- [x] Automatically materialize required teaching occurrences when a plan is added.
- [x] Identify each occurrence by its plan, original week, occurrence number, and stable UUID.
- [x] Derive duration and teaching type from the linked course.
- [x] Define the period length and number of occurrences per week.
- [x] Prevent duplicate requirements through unique constraints and repeatable materialization.
- [x] Preserve identity and source week when moving an occurrence to another target week.
- [x] Keep deliberate cancellations cancelled across repeated expansion; make-up demand is explicitly reopened.
- [x] Link bookings to occurrences without guessing links for existing bookings.
- [x] Read all or only outstanding weekly requirements through an internal paginated backend function.
- [x] Verify recurrence, lifecycle, access rules, and database-reader behavior locally.

Example: `Programming Lab / Group 1 / Week 3 / Occurrence 1`.

**Complete when:** the backend can list exactly which occurrences require scheduling for a selected week, including replacements moved into that week, without duplicating existing or cancelled occurrences.

## 3. Use the existing scheduling dataset

**Status:** complete for the initial MVP on 10 November 2026, based on the user's confirmation that the data is settled in the database. No additional runtime code or database changes are required for this data-preparation milestone. See [dataset readiness and scope](docs/backend/scheduling-dataset.md).

- [x] Use the existing rooms, lecturers, students, and intake/group memberships.
- [x] Use the database's courses, offerings, sections, and weekly teaching requirements.
- [x] Retain room capacity, type, and active status as inputs for later availability checks.
- [x] Preserve all student intake memberships for later cross-intake conflict checking.
- [x] Use existing class bookings/reservations when present; an empty booking calendar is valid for initial generation.
- Meeting fixtures and deliberately impossible-arrangement fixtures are deferred, as requested. Artificial room-scarcity or undersized-room stress fixtures are not needed to block this first runnable path.

Dataset readiness is user-confirmed, not an independent live database audit. No seed scripts were rerun, no sample records were inserted, and no hosted data was queried or changed during this step.

**Complete when:** the existing database is accepted as the initial source of scheduling inputs. Loading and validating the actual data is step 4; generating a timetable is step 7.

## 4. Build the scheduling-data loader

**Status:** complete and verified locally on 10 November 2026: 96 backend tests passed (1 optional simulation test skipped), and 258 database checks passed. Apply the new `202611100003_scheduling_snapshot.sql` migration before using the loader against Supabase. See [implementation and usage](docs/backend/scheduling-data-loader.md).

- [x] Load weekly occurrences and expose only those still needing placement through `pending_requirements`.
- [x] Resolve and validate the assigned lecturer identities.
- [x] Resolve class rosters through matching `student_intakes.intake_id` and `group_number`.
- [x] Preserve actual student IDs across intake memberships.
- [x] Deduplicate student IDs and provide actual class sizes.
- [x] Load room type, capacity, and active status without deciding room availability.
- [x] Load scheduled class/meeting bookings and existing class reservations that overlap the week, including bookings beginning before it. Empty meeting data is valid.
- [x] Derive class end times from course duration; use explicit meeting end times.
- [x] Resolve configured opening windows and validate missing or inconsistent database input.
- [x] Produce an immutable engine input using one read-only database snapshot and a content fingerprint.
- [x] Support occurrence views before and after the room-requirement removal patch without inventing a new compatibility policy.

| Input | What the loader must resolve |
| --- | --- |
| Required occurrences | Which lessons still need placement |
| Class rosters | Actual student IDs from intake/group memberships |
| Lecturers | Assigned lecturer for each section |
| Rooms | Type, capacity, and active status |
| Existing bookings | Classes, meetings, and reservations |
| Calendar rules | Permitted dates, hours, and explicit closures; unrestricted start times |

**Complete when:** the engine receives a validated snapshot containing all information required to evaluate placements.

## 5. Build a standalone booking validator

**Status:** complete and verified locally on 10 November 2026. Focused validator suite: 52 passed; full backend suite: 148 passed, 1 optional test skipped. No new migration is needed. See [booking validation](docs/backend/booking-validation.md).

- [x] Accept an occurrence, aware start, room, and explicit schedule/reschedule mode; derive end time from course duration.
- [x] Check lecturer overlaps across classes and meetings.
- [x] Check actual student overlaps across intake memberships and meeting attendance.
- [x] Check room overlaps across classes, meetings, and fixed reservations.
- [x] Check room capacity, active status, and the user-confirmed configurable course-to-room policy.
- [x] Check full duration against the selected week and effective opening windows; apply no break restrictions.
- [x] Ignore cancelled bookings and require explicit reopening of cancelled teaching demand.
- [x] Exclude only the occurrence's matching original class booking in reschedule mode.
- [x] Use half-open intervals so adjacent classes do not overlap.
- [x] Return structured rejection reasons, conflicting booking references, and student-conflict counts.
- [x] Capture room policy in the input fingerprint so changes invalidate earlier preview context.

**Complete when:** every proposed booking receives a clear valid/invalid result with specific reasons.

## 6. Generate candidate placements

**Status:** complete and verified locally on 10 November 2026. Candidate and validator suites: 76 passed; full backend suite: 172 passed, 1 optional simulation test skipped. No new migration. See [candidate generation](docs/backend/candidate-generation.md).

- [x] Calculate complete room-specific start-time ranges with inclusive boundaries and no preset start grid.
- [x] Share validator checks for room activity, captured compatibility policy, and capacity.
- [x] Preserve exact durations and microsecond start boundaries, including single-start exact-fit gaps.
- [x] Subtract merged lecturer, student, and room booking intervals from effective teaching windows.
- [x] Return structured diagnostics for lifecycle, closed windows, unsuitable rooms, and insufficient uninterrupted free time.
- [x] Include the explicit captured horizon and snapshot revision in results.
- [x] Generate independent candidates for every pending occurrence and identify blocked occurrences; joint assignment remains step 7.

**Complete when:** every occurrence has a list of possible placements or a clear explanation of why none exists.

## 7. Implement CP-SAT generation for feasibility

**Status:** complete and verified locally on 10 November 2026. Focused solver suite: 29 passed; full backend suite: 201 passed, 1 optional simulation test skipped. OR-Tools is declared in backend requirements and installed locally. No new migration. See [joint CP-SAT scheduling](docs/backend/cp-sat-scheduling.md).

- [x] Build a joint feasibility model using Google OR-Tools CP-SAT.
- [x] Encode relative integer microseconds exactly, preserving all representable candidate boundaries without preset slots or float rounding.
- [x] Select one room and start per pending occurrence, with the full duration mandatory.
- [x] Enforce no-overlap for shared lecturers, actual students, and room choices among new classes.
- [x] Enforce fixed-booking/reservation/meeting conflicts through internally generated candidate domains.
- [x] Preserve existing bookings and exclude already-scheduled/cancelled demand from regeneration.
- [x] Validate complete solver output against the standalone validator and independently check new-class resource conflicts.
- [x] Configure search time, worker count, and random seed in the existing config file.
- [x] Distinguish successful, infeasible, unresolved, invalid-model, and empty-input outcomes.
- [x] Return no partial assignments when search is unresolved or infeasible.
- [x] Never drop a required occurrence; a missing candidate blocks the entire draft with diagnostics.

Individually valid candidates can still conflict with one another. The solver must consider the complete set of new assignments together.

**Complete when:** the engine returns a complete timetable satisfying every compulsory rule, or an appropriate solver outcome without invalid or silently omitted assignments.

## 8. Add timetable quality objectives

- [ ] Measure idle minutes between each student's first and last class per day; no mandatory breaks apply.
- [ ] Make reducing total student waiting time the first optimization objective.
- [ ] Add lecturer gap reduction as a lower-priority objective.
- [ ] Add room utilization as a further preference.
- [ ] Keep preference priorities configurable.
- [ ] Keep all compulsory rules mandatory regardless of preference scores.
- [ ] Return quality measurements alongside the generated timetable.

Initial preference order:

1. Reduce student waiting time between classes.
2. Reduce lecturer gaps.
3. Improve room utilization.

**Complete when:** valid schedules can be compared using meaningful measurements, such as total student idle minutes, and the configured preferences influence generation.

## 9. Expose generation as a preview operation

- [ ] Add an API operation such as `POST /api/schedules/generate`.
- [ ] Accept a selected teaching week and supported scheduling options.
- [ ] Return proposed assignments, solver status, quality measurements, and diagnostic information.
- [ ] Keep generation separate from committing actual bookings.
- [ ] Associate the preview with its input revision so later data changes can be detected.
- [ ] Make the operation usable through FastAPI's API documentation.

**Complete when:** timetable generation can be demonstrated through the API without a frontend or changes to actual bookings.

## 10. Implement safe timetable saving

- [ ] Add an authorized operation to commit a generated preview.
- [ ] Verify the caller's permission to perform the scheduling operation.
- [ ] Detect stale previews and recheck current data and availability within the transaction.
- [ ] Use a consistent locking strategy for all relevant booking and roster changes.
- [ ] Save assignments and relevant audit information together in one database transaction.
- [ ] Prevent duplicate bookings for the same teaching occurrence.
- [ ] Handle retries safely so repeated submissions do not duplicate assignments.
- [ ] Reject a failed commit without leaving a partially saved timetable.

For the hackathon dataset, a shared scheduling lock is a reasonable starting design, provided all relevant mutations follow the same rules.

**Complete when:** simultaneous requests cannot double-book resources, retries cannot duplicate occurrences, and failed saves leave no partial timetable.

## 11. Add rescheduling, cancellation, and reservations

- [ ] Reuse calendar rules, candidate search, and booking validation.
- [ ] Find and rank alternative placements for an existing occurrence.
- [ ] Keep other classes fixed during ordinary single-class rescheduling.
- [ ] Save a replacement placement and its change history atomically.
- [ ] Preserve the original booking if a replacement fails.
- [ ] Allow deliberate cancellation to release the occurrence's resources.
- [ ] Reserve future placements for the lecturer, attending students, and room.
- [ ] Keep publication state separate from whether a booking occupies resources.
- [ ] Treat future reservations as fixed constraints when generating the rest of that week.
- [ ] Enforce the caller's permission for each cancellation, reschedule, or reservation.

KK's required workflow:

1. Identify the affected class occurrence.
2. Cancel it independently, or request a direct replacement.
3. Search a selected target week.
4. If the week already has classes, suggest valid remaining placements.
5. If the week is unpublished, check existing bookings and reserve a valid placement.
6. Preserve the reservation when generating the remaining timetable later.

**Complete when:** this workflow works through the API, including a replacement reservation in an unpublished week.

## 12. Verify the complete scheduling workflow

- [ ] Verify the acceptance scenarios below with meaningful automated checks.
- [ ] Verify timetable retrieval after a successful commit.
- [ ] Verify compulsory rules again against the generated output using the standalone validator.
- [ ] Exercise simultaneous booking attempts against the transactional save operation.

| Scenario | Expected result |
| --- | --- |
| Two classes share students across different intakes | They cannot overlap |
| Two classes need the only suitable lab | They receive different times |
| No sufficiently large room exists | Clear failure; no invalid assignment |
| A class overlaps an existing meeting | Conflicting placement rejected |
| A future week contains a reservation | Generation preserves it |
| Generation is repeated | No duplicate lessons |
| A deliberately cancelled lesson exists | Generation does not recreate it automatically |
| A booking is cancelled | Its resources become available |
| Two requests claim the same resource | At most one succeeds |
| A replacement booking fails | Original booking remains intact |
| A preview becomes stale | Commit revalidates or rejects it safely |
| Search stops before finding a solution | Report unresolved search, not proven impossibility |
| A required occurrence has no placement | Do not silently return a complete timetable |

**Complete when:** the development dataset passes the full workflow:

`Teaching requirements → generation → preview → commit → timetable retrieval`

All acceptance scenarios must pass before treating the scheduling backend as ready for frontend integration.

## Suggested delivery milestones

| Milestone | Steps | Reviewable result |
| --- | --- | --- |
| Scheduling foundation | 1–4 | Explicit rules, teaching requirements, development data, and validated engine input |
| Placement validation | 5–6 | Explainable booking checks and candidate search |
| Working generation | 7 | Complete, clash-free weekly timetable generation |
| Improved timetable | 8–9 | Quality objectives and a generation preview API |
| Reliable persistence | 10 | Authorized, transactional timetable saving |
| Lecturer workflow | 11 | Rescheduling, cancellation, and future reservations |
| Backend readiness | 12 | Verified generation-to-retrieval workflow and acceptance scenarios |
