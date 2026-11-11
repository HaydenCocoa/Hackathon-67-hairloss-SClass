# Step 3 — Existing database dataset

Date: 10 November 2026 (Asia/Kuala_Lumpur).

Status: complete for the agreed initial MVP, based on user-confirmed database readiness. No new backend code is required for this milestone.

## User direction

The user confirmed the data is settled in the database, deferred the meeting and impossible-arrangement requirements, and requested a working initial system that can be enhanced afterward.

Step 3 therefore accepts the existing dataset rather than generating another synthetic dataset. Runtime scheduling logic belongs to the subsequent milestones.

## Inputs accepted for the initial path

| Input | Use in later scheduling work |
| --- | --- |
| Rooms | Capacity, type, and active status |
| Lecturers | Existing assignments to course offerings |
| Students and intake/group memberships | Actual class rosters and conflicts across intakes |
| Courses | Teaching type and duration |
| Offerings and sections | Intake, group, lecturer, and room requirements |
| Teaching plans and occurrences | Required lessons for the selected target week |
| Existing class bookings/reservations, if any | Occupied resources and already placed occurrences |

The initial booking calendar can be empty. A pre-existing meeting, reservation, or scheduled class is not needed to demonstrate first-time class generation. When existing bookings are present, later loading/validation must account for them.

## Scope changes

- Meeting sample records are not required for step 3.
- A deliberately impossible scheduling dataset is not required for step 3.
- Artificial scarcity and undersized-room stress fixtures can be added during later hardening; normal room metadata remains necessary for valid placement.
- No existing tests or tables were removed. Conflict detection and accurate solver-status handling remain later development requirements.

## What was reviewed and changed

Reviewed the current development checklist, backend record, weekly teaching-plan notes, `supabase/README.md`, and `supabase/seed_courses.sql`.

The repository already contains seeds for rooms, lecturers, students/memberships, and course/offering/section relationships. The course seed defines six teaching components for `APU1F2611CS(SE)`, Group 1. The step 2 migration defines database-backed teaching plans and stable occurrences. Production period values remain database data; no new dates or frequencies are inferred from the seed files.

Only documentation and the project instruction were changed for this step. No seed was rerun, no records were inserted or deleted, and no migration or runtime code was added.

## Evidence and limits

Database readiness is the user's confirmation, not an independently executed live query. This step does not claim that the assistant applied the step 2 migration or inspected hosted rows. Earlier step 2 notes record that no hosted migration was applied by that task; the user's current confirmation supplies dataset readiness for this milestone.

Step 4 must load the actual selected week's persisted occurrences and resolve rosters/resources. If that week has no active teaching plan or required occurrences, report the actual missing/empty input rather than inventing lessons or treating it as proof that a timetable was generated. Existing legacy bookings still require deliberate occurrence reconciliation where applicable, as described in the step 2 notes.

Verification for this change consists of checking documentation links and `git diff --check`. No runtime tests were rerun for documentation-only work, and no live Supabase connectivity or scheduling success is claimed.

## Next milestone

Step 4 implements the scheduling-data loader: read the selected week's demand, resolve lecturers and actual student rosters, load room inventory and existing bookings, and produce validated input for later placement and solver work. It has not been implemented as part of this step 3 update.

References: [backend record](agents.md), [weekly teaching plans](weekly-teaching-plans.md), [database setup and seeds](../../supabase/README.md), [development checklist](../../task_hayden.md).
