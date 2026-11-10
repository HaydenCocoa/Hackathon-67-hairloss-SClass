# Lecturer page

Vue 3 (`<script setup>` single-file components). Opened from the main menu at **`#/lecturer`** (`src/App.vue`).
Every file the Lecturer page needs on the frontend is in this folder, like `student/`.

| File | What it does |
| --- | --- |
| `LecturerPage.vue` | The page: lecturer picker, tabs, loading data, toast. Imports the three components below. |
| `LecturerTimetable.vue` | **View-only** weekly timetable of the courses the selected lecturer teaches. |
| `RescheduleList.vue` | Upcoming classes that can still be moved; "Reschedule" opens the dialog. |
| `RescheduleDialog.vue` | Form for a new date, start time and room. Shows the end time (start + course length). Lists the exact clashes if the server refuses. |
| `lecturerApi.js` | `fetch` calls to `/api/lecturers`, `/api/rooms`, `/api/lecturers/{id}/timetable`, `PATCH /api/lecturers/{id}/sessions/{id}`. |
| `time.js` | Date/time helpers in Asia/Kuala_Lumpur (week maths, 12-hour format, end time). |
| `session.js` | Small helpers: course colour, "Intake · Group n", which rooms fit a class. |
| `lecturer.css` | Google-style theme: white base with blue, red, yellow and light green. Scoped to `.lecturer`, classes start with `lc-`. |
| `lecturer.test.js` | Tests for the logic above: `node --test frontend/src/lecturer/lecturer.test.js` (no packages needed). |

## Notes
- There is no login yet: the lecturer is chosen from the dropdown, and the choice is remembered in the browser.
- The server decides whether a new time is allowed (room, lecturer and student clashes, room type, capacity). The page
  only shows its answer.
- Backend: `backend/app/lecturer/`. Database functions: `supabase/lecturer_functions.sql`.
