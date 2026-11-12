# Project working instructions

## Backend documentation

- Read `docs/backend/agents.md` before backend work.
- Keep `docs/backend/agents.md` as the main backend record. Document requirements, decisions and their reasons, implemented changes, remaining plans, verification results, and unresolved questions or limitations.
- Record meaningful backend work in `docs/backend/` during the same task; documentation is part of completion.
- Put detailed specifications or implementation notes in separate Markdown files under `docs/backend/` and link them from the main record.
- Distinguish completed behavior from proposals and planned work. Report actual test results; do not mark unverified work as complete.
- Keep the "Remaining work" section of `docs/backend/agents.md` aligned with accepted requirements and completed milestones; it replaced the `task_hayden.md` checklist (removed 12 November 2026).
- Never copy credentials, private student records, or other sensitive values into documentation.

## Accepted login rules

- Everyone logs in at `/login` with a Supabase Auth email and password; every other page redirects there when not logged in.
- The backend handles login and keeps the session in httpOnly cookies; no Supabase key or token is sent to the browser.
- Roles come from `admins`, `lecturers` and `students` linked by `auth_user_id`; an account linked to several uses admin > lecturer > student. Unlinked accounts are refused.
- Pages: `/student`, `/lecturer`, `/admin` (empty placeholder owned by another team member). Development pages live under `/admin/development/` and need an admin login.
- Do not change the student or lecturer page components for login work; only route users to them. Sign-up and password reset are out of scope.
- Accounts created on the admin page get a temporary password (their code + 4 random digits) and must change it at `/change-password` before using any other page or API (accepted 13 November 2026). The flag is Supabase `app_metadata.must_change_password`; see `docs/backend/login.md`.

## Accepted scheduling rules

- Teaching weekdays and opening hours are defined in `Config/config.json`.
- Initial hours are Monday–Friday, 08:30–18:00, in `Asia/Kuala_Lumpur`.
- Classes can start at any whole minute (accepted 12 November 2026) if the full duration fits within opening hours. Do not introduce a coarser start-time grid without a new requirement.
- Two bookings (classes or meetings) that share a room, lecturer or student must be at least `min_gap_minutes` apart (15 minutes, accepted 12 November 2026; scope confirmed the same day). Do not add other mandatory breaks or travel-time rules without a new requirement.
- Calendar eligibility alone does not establish lecturer, student, or room availability; those checks belong to later booking validation.
- Teaching requirements repeat weekly over a database-defined period. Each lecture/lab section has a plan with a Monday start week, number of weeks, and occurrences per week. Preserve occurrence identity and original week when cancelling or moving it.
- Step 3 uses the existing database dataset, confirmed ready by the user. Meeting and deliberately infeasible dataset fixtures are deferred for the initial MVP; do not add them as completion blockers or invent new hosted sample records.
- The confirmed room policy is configurable: lectures use classrooms/auditoriums; tutorials and labs use classrooms/labs. Auditoriums (`reserved_room_types`) are used only when no other active, permitted room has enough seats (accepted 12 November 2026). Missing or empty mappings (initially `others`) reject placement. Use snapshot room rules, not the removed legacy section field.
- Step 8 preferences (student idle 100, lecturer idle 10, room fit 1) only rank valid timetables; compulsory rules always win. Configure them in `scheduling.quality`.
- A "fewer days on campus" preference and course-offering end dates are deferred (12 November 2026, not a priority). Keep scheduling as it is; do not start either without a new request.
- Every write that moves or creates a class (lecturer page, admin page, timetable save) must follow the same compulsory rules. Reuse the shared validator rather than writing separate checks (see `docs/backend/lecturer-reschedule-review.md`). The admin Reschedule dialog and the lecturer page's move (since 12 November 2026) do this through `scheduling/reschedule.py` (`docs/backend/admin-reschedule-api.md`), and write through the database functions `admin_reschedule_class` / `lecturer_reschedule_class` under the timetable lock; reuse them for other single-class moves.
- Step 9 preview generation requires a selected intake UUID and optionally a group number; omission of the group means all groups in that intake. Since 12 November 2026 it also accepts several intake UUIDs (`intake_ids`, all their groups), scheduled together in one preview and one save; the admin page `/admin/schedule` uses this. Preserve all existing class/meeting/reservation bookings and cross-intake student conflicts. Since 12 November 2026 the generate and save API is an admin-only production endpoint (admin login and a same-site `Origin`; it works on Vercel), at the user's request. Keep the development test page local-development only (development mode, direct localhost, admin login) under `/admin/development/`.
