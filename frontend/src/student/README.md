# Student Page (Bi Jin)

Open **http://127.0.0.1:5173/#/student** (or click *Student timetable* in the main menu sidebar).

## What it does

- Weekly timetable grid (Mon–Fri, plus weekend only when something is scheduled) with a red "now" line, and a List view for small screens.
- Shows only the student's own classes: sections whose intake **and** group number match the student's `student_intakes` memberships.
- Cancelled classes are red and struck through; rescheduled classes get a yellow "Moved" badge. The side panel lists every cancellation and reschedule from the last 14 days.
- Click any class for details: time, room, lecturer, intake/group, and what changed (old time/room, reason).
- Meetings the student is invited to (`meeting_students`) appear as dashed green blocks.
- "Try with sample data" loads a built-in demo week, so the page can be shown before real classes exist in Supabase.

## Files

| File | Purpose |
| --- | --- |
| `StudentPage.vue` | Page layout, temporary sign-in, week navigation, summary, side panel |
| `WeekTimetable.vue` | Calendar grid (handles overlapping classes side by side) |
| `AgendaList.vue` | List view grouped by day |
| `SessionDialog.vue` | Class / meeting details pop-up |
| `studentApi.js` | Calls the FastAPI endpoint |
| `demoData.js` | Sample week in the same shape as the API response |
| `student.css` | Theme colours (white, blue, red, yellow, green), scoped under `.sp` |
| `../../../backend/app/student.py` | FastAPI routes (see below) |

## API

- `GET /api/student/{student_code}`: profile and intake memberships
- `GET /api/student/{student_code}/timetable?start=ISO&end=ISO`: classes, meetings and recent changes in the range (max 31 days)

Try it at http://127.0.0.1:8000/docs. The backend uses the server key from `.env`, so it filters by membership itself.

## Notes for the team

- **Login (Hayden):** until login exists, the student types their code (stored in `localStorage`). When login is ready, render `<StudentPage :student-code="signedInCode" />`. The backend should then take the student from the session instead of the URL, so students can only view their own timetable (see the TODO in `student.py`).
- **Reschedule/cancel (Ting Ju / Edward):** when writing `schedule_changes`, put `starts_at` and `room_id` in `old_values` / `new_values` (e.g. `{"starts_at": "...", "room_id": "..."}`). The Student Page reads these keys to show "was → now". Set `class_sessions.status = 'cancelled'` for cancellations.
- Request-a-meeting (optional feature) is not built yet: `meeting_sessions.status` only allows `scheduled`/`cancelled`, so a request/approval status or table is needed first.
