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

The admin page's reschedule (`admin_reschedule_class`) has the same gaps for opening hours and the 15-minute gap. Room type, the auditorium rule and the `rescheduled` status were fixed on 12 November by [202611120003](../../supabase/migrations/202611120003_admin_reschedule_fixes.sql).

## Fixed during this review

- `GET /api/lecturers/{id}/timetable` returned a made-up `intake_code` (`"CS-2024"`) and `student_count` (`30`) for every class. It now reads the intake code from `intakes` and counts the students in the class's intake and group (`group_facts`). The page's room list now filters by the real group size. Test: `test_lecturer_timetable_shows_the_real_intake_code_and_group_size`.

## Not verified

None of this was run against hosted Supabase or in a real browser. Findings 4 and 6 are timing problems found by reading the code; they were not reproduced.
