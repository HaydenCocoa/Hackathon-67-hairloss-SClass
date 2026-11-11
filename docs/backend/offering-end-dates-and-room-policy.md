# Review: offering end dates and system-defined room suitability

Date: 10 November 2026 (Asia/Kuala_Lumpur).

Status: evaluation and recommendations only. The user proposed these changes and requested assessment. No database migration, application behavior, room policy, seed data, or hosted records were changed by this review.

## Assessment

| User proposal | Assessment | Recommended condition |
| --- | --- | --- |
| Add an ending date to each course offering | Suitable: the same course may finish at different times for different intakes | Define an inclusive last teaching date in the campus timezone, and enforce it in requirement generation and booking validation |
| Defer public holiday and semester-break enhancements | Suitable for the initial scope | Keep the existing configurable teaching calendar and explicit closures; do not claim automatic holiday or break awareness |
| Remove `class_sections.required_room_type` | Suitable if the system owns an explicit replacement policy | Derive allowed room types from teaching type; continue validating actual room type, capacity, active status, and availability |

These recommendations are not implemented or marked as completed milestones. The precise cutoff/make-up rules and room compatibility mapping still need confirmation.

## Offering end date

Recommend `course_offerings.teaching_end_date DATE`. An offering is the correct scope because different intakes can finish the same subject at different dates. In the current model, lecture/lab/tutorial are separate course rows and offerings, so each component has its own cutoff; use matching values when the subject components finish together.

Recommended initial semantics:

- The date is inclusive in `Asia/Kuala_Lumpur`. For an end date of 30 November 2026, a class on that date may be eligible; 1 December is outside the offering period.
- The full scheduled interval must fit within the offering period and the existing configured daily opening hours. Compute the upper boundary as local midnight at the start of the following date, converted to a timezone-aware timestamp. Do not depend on the database session's implicit timezone.
- Skip ordinary recurring demand whose target dates fall after the cutoff. A week overlapping the cutoff can still contain eligible days; do not reject or accept the entire week solely from its Monday date.
- Offering expiry does not delete historical sessions or cancel already-created teaching obligations. An unfulfilled occurrence that cannot be placed before the cutoff must remain visible as unresolved demand.
- Recommended default for discussion: the cutoff also blocks make-up/replacement bookings. A later make-up class requires an explicit, authorized extension or a future exception policy. If the user intends the date only to stop ordinary recurrence, model that separately from the final allowed booking date.
- Shortening a date must check existing future sessions, reservations, plans, and outstanding occurrences. Reject or require explicit reconciliation when it would invalidate them; do not silently delete or hide them.
- A teaching start date is also useful, but is an additional recommendation rather than part of the user's current request. If the existing plan supplies the start, validate the offering end against that plan instead of inventing a second independent start boundary.
- Existing sample data has no agreed end dates. Do not fabricate dates from intake codes. Backfill supplied dates before treating the cutoff as mandatory. If transitional NULLs are permitted, the generation policy must explicitly reject unresolved boundaries or require another configured teaching-period bound; NULL must not silently mean unlimited teaching.

### Teaching-plan consistency

The working tree contains a draft teaching-plan migration using `first_week_start` and `week_count`. Those values already define a recurrence period. An offering end date should be the overall boundary, and section teaching plans must fit within it; otherwise the two sources can disagree. Prefer deriving the plan's last week from explicit dates or validating both representations whenever either is changed.

An end date alone does not define which teaching days, class types, or occurrence counts are required in each week. The recurring-plan-versus-explicit-weekly-demand decision remains separate. Stable occurrence IDs and cancellation/replacement lifecycle rules still apply.

## System-defined room suitability

Removing a section-level room requirement is reasonable when requirements are uniform by teaching type. The system still needs explicit compatibility rules; removing the column does not make every room suitable.

Proposed starting policy, awaiting confirmation:

Historical proposal: the user later confirmed a different mapping in step 5. Current behavior is lecture → classroom/auditorium; tutorial and lab → classroom/lab. See [accepted policy and validator](booking-validation.md). The table below is retained as proposal history, not active policy.

| `courses.course_type` | Allowed `rooms.room_type` values |
| --- | --- |
| `lab` | `lab` |
| `lecture` | `classroom`, `auditorium` |
| `tutorial` | `classroom`, `auditorium` |
| `others` | Must have an explicit configured mapping; no silent fallback |

Keep `rooms.room_type`, capacity, and active status: they describe the real facility. Keep the compatibility mapping in one versioned system configuration so candidate generation, preview, rescheduling, and transactional commits use the same rules. Changes to that policy must invalidate or revalidate stale previews.

Room choice must still satisfy capacity for the full actual roster, including shared lectures; room availability, lecturer availability, and student availability are later checks. A public holiday or daily-calendar check alone establishes none of these.

The tradeoff is less per-section flexibility. A future specialist lab or equipment-dependent lesson may need capability tags or an explicit override. Such exceptions are deferred rather than represented by arbitrary room assignments today.

## Files affected by a later implementation

- [Fresh schema](../../supabase/schema.sql): add the agreed date field and remove the room requirement only alongside its replacement behavior.
- [Course seed](../../supabase/seed_courses.sql): supply agreed end dates and stop inserting/updating `required_room_type`.
- `class_session_details` and any occurrence view: update exposed fields and add the offering boundary where needed.
- [Teaching-plan migration](../../supabase/migrations/202611100001_teaching_requirements.sql): the later 11 November update removed `required_room_type` dependencies from the metadata-protection trigger and occurrence view. Offering end-date bounds remain deferred.
- [Draft requirements loader](../../backend/app/scheduling/requirements.py): update its input/output contract and derive suitability through the shared policy rather than a mandatory section field.
- SQL/Python fixtures, integration checks, schema upgrades, ERD documentation, and downstream readers need coordinated changes. Already-applied migrations should be followed by a new upgrade rather than rewritten.
- [Development checklist](../../task_hayden.md): decisions are pending; implementation and verification remain unchecked.

## Required verification when implemented

- A class fitting on the final permitted date is accepted; a later booking is rejected.
- A week straddling the cutoff only yields eligible placement dates.
- Start/end conversion uses the campus timezone even when the database/client timezone differs.
- Shortening the date cannot silently invalidate existing bookings or discard pending obligations.
- Make-up bookings obey the chosen cutoff/extension policy.
- Draft plan bounds cannot disagree with the offering boundary.
- Labs cannot be placed into ordinary classrooms; lectures/tutorials can use only their configured compatible room types.
- Unknown teaching types or missing mappings fail with a clear configuration/validation reason.
- Room capacity, active state, and all resource conflicts remain mandatory.
- Removal of the column leaves no stale view, trigger, loader, seed, or API dependency.

## Verification performed for this review

Read the current schema, course seed, configuration, backend record/checklist, teaching-requirements discussion, and the uncommitted draft migration/loader. This is documentation-only assessment; runtime tests were not rerun, and the draft files were not validated or marked complete by this review.

`git diff --check` passed, and local links in this assessment, the main backend record, and the checklist resolved.

References: [PostgreSQL date/time types](https://www.postgresql.org/docs/current/datatype-datetime.html) and [cross-table constraint limitations](https://www.postgresql.org/docs/current/ddl-constraints.html). The latter means an offering cutoff cannot be enforced on a session through a simple row-only CHECK; a later implementation needs coordinated validation and transactional/database enforcement.
