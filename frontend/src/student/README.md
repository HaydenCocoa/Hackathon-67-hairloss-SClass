# Student Page (Bi Jin)

Log in as a student and you land on **http://127.0.0.1:5173/student**. App.vue passes the signed-in student's code as `<StudentPage :student-code="session.code" />`.

## What it does

- Weekly timetable grid (Mon–Fri, plus weekend only when something is scheduled) with a red "now" line, and a List view for small screens.
- Shows only the student's own classes: sections whose intake **and** group number match the student's `student_intakes` memberships.
- Cancelled classes are red and struck through; rescheduled classes get a yellow "Moved" badge. The side panel lists every cancellation and reschedule from the last 14 days.
- Click any class for details: time, room, lecturer, intake/group, and what changed (old time/room, reason).
- Meetings the student is invited to (`meeting_students`) appear as dashed green blocks.
- If the login expires, the page sends the user back to `/login` and returns to `/student` afterwards.
- If the account has no linked student record, the page says so instead of showing an empty timetable.

## Files

| File | Purpose |
| --- | --- |
| `StudentPage.vue` | Page layout, week navigation, summary, side panel |
| `WeekTimetable.vue` | Calendar grid (handles overlapping classes side by side) |
| `AgendaList.vue` | List view grouped by day |
| `SessionDialog.vue` | Class / meeting details pop-up |
| `studentApi.js` | Calls the FastAPI endpoint |
| `demoData.js` | Sample week in the same shape as the API response (not used by the page; kept for tests/demos) |
| `student.css` | Theme colours (white, blue, red, yellow, green), scoped under `.sp` |
| `../../../backend/app/student.py` | FastAPI routes (see below) |

## API

- `GET /api/student/{student_code}`: profile and intake memberships
- `GET /api/student/{student_code}/timetable?start=ISO&end=ISO`: classes, meetings and recent changes in the range (max 31 days)

Try it at http://127.0.0.1:8000/docs. The backend uses the server key from `.env`, so it filters by membership itself.

## Notes for the team

- **Login (Hayden):** done. The backend only lets a student open their own code (admins can open any).
- **Reschedule/cancel (Ting Ju / Edward):** when writing `schedule_changes`, put `starts_at` and `room_id` in `old_values` / `new_values` (e.g. `{"starts_at": "...", "room_id": "..."}`). The Student Page reads these keys to show "was → now". Set `class_sessions.status = 'cancelled'` for cancellations.
- Request-a-meeting (optional feature) is not built yet: `meeting_sessions.status` only allows `scheduled`/`cancelled`, so a request/approval status or table is needed first.
