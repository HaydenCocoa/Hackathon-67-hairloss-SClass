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
