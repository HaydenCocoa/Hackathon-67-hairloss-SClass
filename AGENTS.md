# Project working instructions

## Backend documentation

- Read `docs/backend/agents.md` before backend work.
- Keep `docs/backend/agents.md` as the main backend record. Document requirements, decisions and their reasons, implemented changes, remaining plans, verification results, and unresolved questions or limitations.
- Record meaningful backend work in `docs/backend/` during the same task; documentation is part of completion.
- Put detailed specifications or implementation notes in separate Markdown files under `docs/backend/` and link them from the main record.
- Distinguish completed behavior from proposals and planned work. Report actual test results; do not mark unverified work as complete.
- Keep the backend development checklist in `task_hayden.md` aligned with accepted requirements and completed milestones.
- Never copy credentials, private student records, or other sensitive values into documentation.

## Accepted scheduling rules

- Teaching weekdays and opening hours are defined in `Config/config.json`.
- Initial hours are Monday–Friday, 08:30–18:00, in `Asia/Kuala_Lumpur`.
- Classes can start at any time if the full duration fits within opening hours. Do not introduce a fixed start-time grid, mandatory break, or travel-time restriction without a new requirement.
- Calendar eligibility alone does not establish lecturer, student, or room availability; those checks belong to later booking validation.
- Teaching requirements repeat weekly over a database-defined period. Each lecture/lab section has a plan with a Monday start week, number of weeks, and occurrences per week. Preserve occurrence identity and original week when cancelling or moving it.
- Step 3 uses the existing database dataset, confirmed ready by the user. Meeting and deliberately infeasible dataset fixtures are deferred for the initial MVP; do not add them as completion blockers or invent new hosted sample records.
- The confirmed room policy is configurable: lectures use classrooms/auditoriums; tutorials and labs use classrooms/labs. Missing or empty mappings (initially `others`) reject placement. Use snapshot room rules, not the removed legacy section field.
