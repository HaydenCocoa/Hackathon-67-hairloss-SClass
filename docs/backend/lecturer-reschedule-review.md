# Step 11 review: lecturer rescheduling

Reviewed: 12 November 2026, on `main` after PR #15. Related: [backend record](agents.md), [rescheduled status](rescheduled-status.md), [booking validation](booking-validation.md), [timetable quality](timetable-quality.md), [login](login.md).

## Scope

The lecturer page's rescheduling was reviewed against the accepted scheduling rules in `AGENTS.md`:

- Backend: [backend/app/lecturer.py](../../backend/app/lecturer.py). Endpoints:
  - `GET /api/lecturers/{id}/timetable`
  - `GET /api/lecturers/{id}/sessions/{id}/suggestions`
  - `PATCH /api/lecturers/{id}/sessions/{id}`
- Frontend: [frontend/src/lecturer/](../../frontend/src/lecturer/).

This is a review: apart from the two placeholder values noted at the end, the findings below are **not fixed**.

## What works

- Only the class's own lecturer, or an admin, can move it.
- Cancelled classes are refused (409). A moved class becomes `rescheduled` and gets a `schedule_changes` row with the user's Supabase id.
- The new end time comes from the course duration in the database, not from the browser.
- The clash checks match the scheduler's way of finding students:
  - Classes clash if they share a room, the lecturer, or an (intake, group) that any of this class's students belongs to. This is exact, because class rosters are defined by intake and group.
  - Meetings clash through `meeting_students`.
  - Cancelled classes and the class being moved are ignored.
- Moving a class into another week keeps its teaching occurrence correct. The `sync_occurrence_booking` trigger updates `target_week_start`.

## Findings

Severity: **High** breaks a compulsory rule or can double-book. **Medium** is wrong behaviour in some cases. **Low** is a robustness or quality issue.

| # | Severity | Finding | Where |
| --- | --- | --- | --- |
| 1 | High | **Opening hours and teaching days are not checked.** `PATCH` accepts any date and time, such as a Sunday or 17:30 for a 2-hour class. The suggestions offer 08:00–19:00 on every day of the week, including weekends. `Config/config.json` says Monday–Friday 08:30–18:00, plus `closed_dates`. | `reschedule_session`, `DAY_START_MIN` (lecturer.py:135, 203–204) |
| 2 | High | **The 15-minute gap is not checked.** The checks only look for overlaps, so a class can be moved to end at 10:00 with the next class in the same room, or for the same lecturer or students, starting at 10:00. The gap is compulsory for any two bookings sharing a room, lecturer or student, including meetings (confirmed 12 November). | `find_conflicts`, `suggest_slots` |
| 3 | High | **Room type and the auditorium rule are not checked** (the code comment says so). The API lets a lecture use a lab, a lab use an auditorium, and an `others` course use any room. The page has the opposite problem. The backend sends `required_room_type: "classroom"` for every class because the column was removed. `roomsFor` therefore lists only classrooms, so a lab class cannot choose a lab and a large lecture cannot choose an auditorium. The suggestions ignore room type as well. | lecturer.py:251, 386; `session.js:20`; `RescheduleDialog.vue:110` |
| 4 | High | **Check, then write, without a lock or a transaction.** The endpoint checks for clashes, then PATCHes `class_sessions`, then POSTs the audit row, all as separate requests. Two moves at the same time, or a move during a timetable save or an admin reschedule, can both pass the check and double-book. The admin function and the save use advisory lock `7280001008`; this endpoint does not. If the audit insert fails, a second PATCH tries to undo the move. If that also fails, the class is moved with no audit row, and the undo can overwrite a change made in between. The PATCH is matched on `id` only, so last write wins. | lecturer.py:463–483 |
| 5 | Medium | **Past classes can be moved through the API.** `get_own_session` only checks the status. `can_reschedule` (start in the future) is enforced only by the page. A class that has already happened, or is in progress, can be moved to a future time. | `get_own_session` (lecturer.py:104) |
| 6 | Medium | **The lecturer page hard-codes a lecturer.** `loadLecturers` first sets a fixed UUID and the name "Ahmad Hakim", which starts timetable requests for that lecturer. For anyone else these return 403. If `/api/lecturers` fails, the page keeps showing that lecturer's name. `loadWeek` and `loadUpcoming` ignore late answers but not late errors, so a slow 403 can leave an error message on screen beside the correct timetable. | `LecturerPage.vue:59–63, 100` |
| 7 | Medium | **Error handling leaks text and loses status codes.** `Supabase.get` catches its own `HTTPException(500, "Database error")` and raises it again as `"Failed to reach Supabase: 500: Database error"`. Exception text goes to the browser (`str(e)` at lecturer.py:70 and 398), and provider response bodies are printed to the console. The scheduling code's safe logging does not do this. | lecturer.py:60–70, 395–398 |
| 8 | Low | **The value that is checked is not the value that is written.** The time is validated by parsing it (`strptime` accepts `9:5`; `date.fromisoformat` accepts `20261120`). The PATCH then writes the raw strings (`20261120T9:5:00+08:00`) instead of the validated `new_start`, so a valid check can be followed by a 500 or an odd audit value. | lecturer.py:446 |
| 9 | Low | **IDs are not validated.** `lecturer_id`, `session_id` and `room_id` are plain strings, so a malformed id gives a 500 from PostgREST instead of a 422. | endpoint signatures, `RescheduleRequest` |
| 10 | Low | **Moving a class to its current time and room is allowed.** It still marks the class `rescheduled` and writes an audit row. | `reschedule_session` |
| 11 | Low | **The teaching plan and offering period are not checked.** A class can be moved to any future week, outside its plan's weeks or after the course ends. End dates are accepted but not built yet (see the backend record). | `reschedule_session` |
| 12 | Low | **The suggestions endpoint is not used.** No page calls `/suggestions`. Its "free" slots break findings 1–3, so it should be fixed before the page uses it. | `suggest_slots`, `lecturerApi.js:64` |
| 13 | Low | **Wrong labels on the page:** a "← Main menu" link (the menu was removed), and "Showing classroom rooms" text that follows from finding 3. | `LecturerPage.vue:156`, `RescheduleDialog.vue:110` |

## Recommended fix

Findings 1–5, 8, 10 and 12 go away if the endpoint reuses the scheduling engine, as step 11 planned, instead of its own checks:

1. Load the target week with `load_scheduling_snapshot`. When the move changes week, also load the original week.
2. Check the move with `BookingValidator` in `mode="reschedule"`. It covers opening hours, closed dates, whole minutes, room type and capacity, the auditorium rule, the 15-minute gap, and lecturer, student and room clashes including meetings. It ignores only the class's own original booking.
3. Build suggestions with `CandidateGenerator`, which uses the same rules, and rank them close to the requested time.
4. Write the move and its audit row in one database transaction under advisory lock `7280001008`. Either:
   - extend `admin_reschedule_class` for lecturers, using a `lecturer_reschedule_class` function with an ownership check, or
   - give the backend's PATCH an expected start and room, as the admin function already does.
5. Send the allowed room types (from `scheduling.room_compatibility`) to the page instead of `required_room_type`.

**Update, 12 November 2026:** steps 1–3 now exist for the admin page as `GET /api/admin/timetable/{id}/availability` and `POST /api/admin/timetable/{id}/reschedule` ([admin rescheduling API](admin-reschedule-api.md)), and step 4 uses `admin_reschedule_class`. The lecturer endpoint can be switched to the same code (with an ownership check).

The admin page's reschedule (`admin_reschedule_class`) has the same gaps for opening hours and the 15-minute gap when it is called directly (the older `PUT /api/admin/timetable/{id}`). Room type, the auditorium rule and the `rescheduled` status were fixed on 12 November by [202611120003](../../supabase/migrations/202611120003_admin_reschedule_fixes.sql).

## Re-check after the lecturer page update (12 November 2026)

At the user's request, the lecturer code merged into `main` in PR #18 (commits `cffbd89`, `4bbc7cf` and `00e0a83`) was checked against the findings above. This was done by reading the code and running the existing tests; no lecturer code was changed.

| # | Status now | Notes |
| --- | --- | --- |
| 1 | **Partly fixed** | Weekends and the closing time are now refused, and the suggestions use Monday–Friday only. But the opening time is hard-coded as **08:00**, while `Config/config.json` says **08:30**, so a class can be moved to start between 08:00 and 08:29. `closed_dates` and the per-day hours are not read from the config. |
| 2 | Fixed | A 15-minute gap is checked for the room, the lecturer, the students and meetings (hard-coded `GAP`, not `min_gap_minutes`). |
| 3 | **Partly fixed, with wrong rules** | Room type is now checked, but against a hard-coded table that differs from the accepted policy: tutorials get classrooms only (accepted: classrooms or labs), labs get labs only (accepted: classrooms or labs), and `others` gets classrooms or auditoriums (accepted: no rooms, so it is refused). The auditorium rule (only when no other room has enough seats) is not checked. |
| 4 | **Not fixed** | An `asyncio.Lock` now serialises moves within one backend process. It does not stop another process (each Vercel instance is separate), a timetable save, or an admin move. The move and the history row are still two writes with an undo, and the update matches on `id` only. |
| 5 | Fixed | A class that has started is refused (409), and so is a new start in the past. |
| 6 | Fixed | The hard-coded lecturer is gone; the page uses `/api/lecturers` and the saved choice. |
| 7 | **Not fixed** | Error replies still include exception and provider text (`str(e)`, `res.text[:300]`), and responses are printed to the console. |
| 8 | Fixed | The validated `new_start` is written. |
| 9 | Not fixed | IDs are still plain strings (500 instead of 422 for a malformed id). |
| 10 | Fixed | A move to the same time and room is refused (422). |
| 11 | Not fixed | Deferred with course end dates. |
| 12 | Fixed | The page now shows the suggestions (every 30 minutes), using the same rules as the checks, including the gaps in 1 and 3. |
| 13 | Fixed | The "Main menu" link and the "classroom rooms" text are gone. |

**Regression:** commit `00e0a83` brought back the made-up `intake_code` (`"CS-2024"`) and `student_count` (`30`) that this review had fixed (see below), so `test_lecturer_timetable_shows_the_real_intake_code_and_group_size` fails on `main`.

**Done the same day (see "Fix" below).** Recommendation was: switch `PATCH /api/lecturers/{id}/sessions/{id}` and the suggestions to `scheduling/reschedule.py` (engine checks with the config's hours, room policy and gap) plus a database function with an ownership check under advisory lock `7280001008`. That fixes 1, 3, 4, 7 and 9 together, and restores the real intake code and group size. Not started: the lecturer page belongs to a teammate.

## Fix (12 November 2026)

At the user's request, the five open areas from the re-check above were fixed, and nothing else: findings 1, 3, 4 and 7, and the lost intake-code/group-size fix. Findings 9 (ID validation) and 11 (plan/offering period) stay open.

| Area | Before | Fix | Where |
| --- | --- | --- | --- |
| 1. Opening time | 08:00–18:00 and Monday–Friday hard-coded; `closed_dates` ignored | The move is checked with the scheduling engine (`BookingValidator`), and the suggestions use its candidate ranges and opening windows. Both read `Config/config.json` (08:30–18:00, per-day hours, closed dates). The page's own start-time check, hint text and demo data now say 08:30. | `lecturer.py` (`reschedule_session`, `suggest_slots`); `frontend/src/lecturer/time.js`, `RescheduleDialog.vue`, `demoData.js` |
| 3. Room rules | Hard-coded table (tutorial: classroom; lab: lab; others: classroom or auditorium); no auditorium rule | The engine applies `scheduling.room_compatibility` (lecture: classroom or auditorium; tutorial and lab: classroom or lab; others: none), capacity, and `reserved_room_types` (an auditorium only when no other permitted room seats the class). The timetable's `allowed_room_types` come from the same config. | same |
| 4. Locking | Per-process `asyncio.Lock`; a PATCH and a separate history insert with the server key; undo on failure | The backend calls `public.lecturer_reschedule_class` (new migration [202611120004](../../supabase/migrations/202611120004_lecturer_reschedule.sql)) as the logged-in lecturer, or `admin_reschedule_class` for an admin acting for a lecturer. One transaction under advisory lock `7280001008`: expected start/room check, room suitability, clash re-check, the move and the history row. The asyncio lock, the direct PATCH and the undo were removed. | `lecturer.py`, `scheduling/reschedule.py` (`run_move_function`), migration |
| 7. Error text | `str(e)`, `res.text[:300]` and provider bodies sent to the browser and printed | Database reads use the shared client in `student.py`, whose errors carry no provider text. Every lecturer endpoint turns failures into a fixed `{message, conflicts}` reply (`safe_database_error`), and the database function's errors are mapped by code to fixed messages. Only the exception type is logged. | `lecturer.py`, `scheduling/reschedule.py` |
| Regression | `intake_code: "CS-2024"`, `student_count: 30` | `group_facts` restored: the real intake code and the number of students in the class's intake and group. | `lecturer.py` (`get_lecturer_timetable`) |

**How a lecturer move works now:**
1. Check access and the class: it must be theirs, active and not started; the new start must be in the future and different.
2. Load the target week with the engine and run `explain` from `scheduling/reschedule.py`, the same code as the admin dialog. Clashes (room, lecturer, students, including the 15-minute gap) return `409` with `conflicts[]`, as before. Rule problems (hours, closed day, room type, size, auditorium) return `422` with the engine's explanation.
3. Call the database function with the user's own token. A missing reason is recorded as "No reason given".

**Response shapes are unchanged** (`{message, conflicts}`; suggestion and timetable fields), so the lecturer page needed no API change. The suggestions start at each day's opening time and step every 30 minutes, as before.

**Still open (by design):**
- The database function re-checks clashes under the lock but not the gap or opening hours, the same limit as the admin dialog.
- Suggestions load one snapshot per week they cover, so a wide `flex_days` is slower.
- The demo data mirrors the hours and room table, but not the auditorium rule.

**Requires** migration `202611120004` on hosted Supabase ([migration guide](hosted-migrations.md)).

**Verification:** new `backend/tests/test_lecturer_reschedule.py` (22 tests) and `supabase/tests/lecturer-reschedule.test.cjs` (14 PGlite checks); see the [backend record](agents.md).

## Fixed during this review

- `GET /api/lecturers/{id}/timetable` returned a made-up `intake_code` (`"CS-2024"`) and `student_count` (`30`) for every class. It now reads the intake code from `intakes` and counts the students in the class's intake and group (`group_facts`). The page's room list now filters by the real group size. Test: `test_lecturer_timetable_shows_the_real_intake_code_and_group_size`.

## Not verified

None of this was run against hosted Supabase or in a real browser. Findings 4 and 6 are timing problems found by reading the code; they were not reproduced.
