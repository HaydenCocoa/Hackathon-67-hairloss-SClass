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

No database schema or hosted data was changed for step 1. No frontend change was needed.

## Development roadmap and status

| Step | Requirement and completion target | Status |
| --- | --- | --- |
| 1 | Configurable teaching calendar and reusable full-interval eligibility check | Complete; verified |
| 2 | Required teaching occurrences with stable identities, teaching weeks, cancellation, and replacement tracking | Planned; next step |
| 3 | Complete synthetic dataset including scarce rooms, shared students, bookings, and impossible cases | Planned |
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
