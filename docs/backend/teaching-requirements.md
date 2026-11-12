# Step 2 discussion — Database-backed weekly teaching requirements

Date: 10 November 2026 (Asia/Kuala_Lumpur).

Status: historical requirements discussion. The user subsequently confirmed repetition over a defined number of weeks and requested implementation. See [implemented weekly teaching plans](weekly-teaching-plans.md) for the current design, migration, behavior, and verification. The proposals and open questions below describe the earlier discussion, not the current implementation status.

## Aim

Define how the backend knows which class occurrences need to be scheduled for a selected week, using database-backed teaching requirements. An occurrence is one required delivery of a class section, with a stable identity. Its assigned date, time, and room are a separate scheduling result.

The user asked whether weekly occurrences must be fetched from the database because each week's scheduling requirements can differ. The proposed design follows that expectation: the backend reads the selected week's persisted requirements and existing booking state rather than relying on a hard-coded class list or copying the previous timetable.

## Weekly requirements and weekly placements

Two kinds of weekly variation must be distinguished:

- The same set of class types may be required every week, but each week's deliveries are separate occurrences and can receive different times and rooms.
- The required class types or counts may also differ between weeks, such as a lab taking place only in selected weeks.

Illustrative example for one subject/group, not actual university data:

| Teaching week | Required lecture occurrences | Required lab occurrences |
| --- | --- | --- |
| Week 1 | 1 | 1 |
| Week 2 | 1 | 0 |
| Week 3 | 2 | 1 |

The scheduler must read the relevant week's requirements. It must not assume the previous week's timetable determines what should be taught next.

## Existing database facts

Reviewed `supabase/schema.sql`:

- `courses` defines course identity, teaching type, and duration.
- `course_offerings` connects a course to an intake and lecturer.
- `class_sections` identifies a group within that offering and its required room type.
- `class_sessions` records a dated booking with a start time, room, and scheduled/cancelled status.
- The schema currently has no explicit teaching-period calendar, active teaching-week rules, per-week occurrence requirements, or stable requirement identity linked to a booking.

Existing `class_sessions` can tell the backend what has been booked. They cannot by themselves tell it every class that should exist in an unscheduled week, because those bookings have not been created yet.

## Proposed data flow

1. Select a target calendar week and resolve any applicable intake/teaching-period context.
2. Read teaching requirements applicable to that week from the database.
3. Identify each required occurrence and resolve its section, course duration, assigned lecturer, and room requirements.
4. Reconcile those requirements with existing bookings and explicit lifecycle decisions. Do not duplicate an occurrence that has already been placed or deliberately removed from demand.
5. Include make-up occurrences explicitly moved into the target week, while retaining their original identity and source requirement.
6. Return the remaining requirements as input to later candidate generation and CP-SAT scheduling.

Steps 2 and 4 in the overall development checklist have different responsibilities: step 2 defines the requirement model and how a week's required occurrences are identified; step 4 later assembles the complete scheduling snapshot, including all students, resources, and competing bookings.

## Proposed authoring approach — awaiting user choice

Recommendation: maintain a recurring weekly teaching plan in the database, with explicit exceptions for particular weeks. Materialize stable occurrence records before they are booked, rather than creating fresh identities whenever the solver runs.

Alternative: explicitly author every week's required occurrences in the database, without a recurring default. This is direct and flexible but requires more data entry.

Whichever authoring approach is chosen, the scheduler should ultimately consume a concrete, database-backed list of occurrences for the selected week. Recurrence expansion must not recreate duplicates on repeated generation.

Exact table names, columns, recurrence expansion, teaching-period boundaries, uniqueness rules, and occurrence lifecycle remain unimplemented proposals.

## Identity and lifecycle requirements to resolve

- Keep the occurrence's identity stable across generation retries and rescheduling.
- Distinguish the original teaching week from the week in which a replacement is scheduled.
- Define whether a cancelled class removes the teaching obligation or leaves an obligation awaiting a make-up class. These are distinct actions and must not be inferred solely from a cancelled booking.
- Define how calendar dates map to teaching weeks, particularly when intakes have different start dates.
- Define which role maintains the teaching plan and weekly exceptions.

## Completion target

Step 2 is complete only after the chosen model is implemented and verified: for a selected week, the backend can identify the exact required occurrences, their existing placement/lifecycle state, and which still require scheduling, without duplicates or unintended recreation of cancelled/replaced lessons.

## Verification for this discussion

- Read the backend record, the step 2 checklist, and current schema definitions.
- Confirmed that course/section definitions and dated bookings exist, while explicit weekly demand does not.
- Documentation changes only; runtime tests are not required for this discussion. Earlier step 1 test results are historical and are not a claim that step 2 is implemented.
- `git diff --check` passed and local documentation links resolved using PowerShell. An initial Python-based link check could not launch because `.venv` currently references a missing base Python executable; this environment issue must be addressed before future runtime verification.
