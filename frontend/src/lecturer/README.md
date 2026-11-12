# Lecturer page
Vue 3 (`<script setup>`). Opened at **`#/lecturer`** (`src/App.vue`). Everything lives in this folder.

| File | What it does |
| --- | --- |
| `LecturerPage.vue` | The page: lecturer picker, Timetable and Reschedule tabs. |
| `LecturerTimetable.vue` | Read-only week view of the classes the lecturer teaches. |
| `RescheduleList.vue` | Upcoming classes that can still be moved. |
| `RescheduleDialog.vue` | Step 1: the lecturer writes when they want the class. Step 2: pick one of the times the backend recommends. |
| `SlotSuggestions.vue` | The list of recommended times and rooms. |
| `lecturerApi.js` | Calls to the FastAPI backend (timetable, suggestions, reschedule). |
| `dataSource.js`, `demoData.js` | Optional demo data. `frontend/.env.local` with `VITE_LECTURER_DEMO=true` uses it instead of the backend. |
| `session.js`, `time.js` | Small helpers (colours, labels, Kuala Lumpur dates and times). |
| `lecturer.test.js` | `node --test frontend/src/lecturer/lecturer.test.js` |

## Rules (enforced by the database function `lecturer_reschedule_class`, see `supabase/reschedule_rules.sql`)

- Monday to Friday, 08:00 to 18:00 (Malaysia time); a class must finish by 18:00.
- At least 15 minutes between classes of the same room, the same lecturer and the same students.
- Room type follows the course type: lecture → classroom or auditorium, tutorial → classroom, lab → lab.
- The room must be active and seat the whole group.
- A moved class gets status `rescheduled` and a row in `schedule_changes`, in the same transaction.

The recommendations come from `GET /api/lecturers/{id}/sessions/{id}/suggestions`; the backend only offers times that follow these rules.
The page never writes a clash: the final move is checked again by the database.
=======
Vue 3 (`<script setup>` single-file components). Log in as a lecturer at **`/login`**; lecturers are sent to **`/lecturer`** (old `#/lecturer` links redirect there).
Every file the Lecturer page needs on the frontend is in this folder, like `student/`.

| File | What it does |
| --- | --- |
| `LecturerPage.vue` | The page: lecturer picker, tabs, loading data, toast. Imports the three components below. |
| `LecturerTimetable.vue` | **View-only** weekly timetable of the courses the selected lecturer teaches. |
| `RescheduleList.vue` | Upcoming classes that can still be moved; "Reschedule" opens the dialog. |
| `RescheduleDialog.vue` | Form for a new date, start time and room. Shows the end time (start + course length). Lists the exact clashes if the server refuses. |
| `lecturerApi.js` | `fetch` calls to `/api/lecturers`, `/api/rooms`, `/api/lecturers/{id}/timetable`, `PATCH /api/lecturers/{id}/sessions/{id}` and the (not yet used) `/suggestions` endpoint. |
| `time.js` | Date/time helpers in Asia/Kuala_Lumpur (week maths, 12-hour format, end time). |
| `session.js` | Small helpers: course colour, "Intake · Group n", which rooms fit a class. |
| `lecturer.css` | Google-style theme: white base with blue, red, yellow and light green. Scoped to `.lecturer`, classes start with `lc-`. |
| `lecturer.test.js` | Tests for the logic above: `node --test frontend/src/lecturer/lecturer.test.js` (no packages needed). |

## Notes
- Login is required. The backend only lets a lecturer read and move their own classes (admins may act for any lecturer); the dropdown lists just the logged-in lecturer.
- The server decides whether a new time is allowed. Today it checks room, lecturer and student clashes (classes and meetings), room capacity and that the room is active. It does **not** yet check opening hours, the 15-minute gap, the room type or the auditorium rule; see the [step 11 review](../../../docs/backend/lecturer-reschedule-review.md).
- A moved class gets the status `rescheduled` and a `schedule_changes` row.
- Backend: `backend/app/lecturer.py`. There are no lecturer database functions; the admin page's reschedule uses `public.admin_reschedule_class` instead.
