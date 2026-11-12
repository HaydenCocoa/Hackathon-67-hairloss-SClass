# Admin rescheduling API

Added 12 November 2026 (branch `feature-admin-room-timetable`). Code: [backend/app/scheduling/reschedule.py](../../backend/app/scheduling/reschedule.py). Tests: [backend/tests/test_admin_reschedule.py](../../backend/tests/test_admin_reschedule.py). Used by the admin page's **Reschedule** dialog (Admin > Timetable). Related: [backend record](agents.md), [step 11 review](lecturer-reschedule-review.md), [booking validation](booking-validation.md), [candidate generation](candidate-generation.md), [migrations](hosted-migrations.md).

## Purpose

Move one existing class to another start time and/or room, with the **same compulsory rules as timetable generation**:
- opening hours, closed dates and weekends;
- whole-minute starts;
- room type, capacity and the auditorium rule;
- the 15-minute gap;
- no clash for the room, the lecturer or any student (classes and meetings, across all intakes).

Two endpoints:

| Method / path | Use |
| --- | --- |
| `GET /api/admin/timetable/{session_id}/availability?date=YYYY-MM-DD[&start=HH:MM]` | Which rooms and start times are free on a day; with `start`, why each room is or is not free at that time. Read-only. |
| `POST /api/admin/timetable/{session_id}/reschedule` | Move the class. Re-checks the move, then saves it with its change history in one database transaction. |

Both need a logged-in **administrator** (login session cookie). They answer `401 AUTH_REQUIRED` without a login and `403 ADMIN_REQUIRED` for other roles. They are not restricted to the development server, so they also work on the production deployment. The `POST` also refuses a browser `Origin` from another site (`403 ORIGIN_NOT_ALLOWED`, see [production access](vercel-deployment.md#scheduling-on-vercel-since-12-november-2026)). Responses use `Cache-Control: no-store`. Errors are `{"detail": {"code", "message", "request_id"}}`, and every request gets an `X-Request-ID` and safe traces ([scheduling logging](scheduling-logging.md)). No IDs, rosters or provider text are logged.

## How it works (reuses the scheduling engine)

1. Read the class from `class_session_details`.
   - It must be `scheduled` or `rescheduled` (otherwise `409 CLASS_NOT_ACTIVE`).
   - It must not have started yet (otherwise `409 CLASS_STARTED`).
   - Its roster is every student in its intake and group (`student_intakes`).
2. Load the **target** week (the week containing `date`, or the new start) with `load_scheduling_snapshot`.
3. `moving_snapshot`:
   - remove the class's own current booking (so it never blocks itself);
   - make the class the snapshot's only class to place.
   
   The class does not need a teaching occurrence, and it can move into another week.
4. Explain each room at one time with `BookingValidator`, and the day's free start ranges per room with `CandidateGenerator`. These are the same code paths as generation and saving.

## `GET …/availability`

| Query | Meaning |
| --- | --- |
| `date` (required) | Campus date (`Asia/Kuala_Lumpur`) to check |
| `start` (optional) | Campus start time `HH:MM` to explain in detail |

Response (`Availability`):

| Field | Meaning |
| --- | --- |
| `session_id`, `date`, `timezone`, `duration_minutes` | The class and day |
| `student_count` | Students in the class (its intake and group): the seats a room needs (added 12 November 2026) |
| `status` | The class's booking status: `scheduled`, or `rescheduled` if it was moved before |
| `step_minutes` | Spacing of the offered start times: **15** (the API itself accepts any whole minute) |
| `rooms[]` | Every room: `id`, `name`, `building`, `room_type`, `capacity`, `is_active`, `suitable`, `issues[]`. `suitable` is false when the room can **never** take this class (`ROOM_INACTIVE`, `ROOM_TOO_SMALL`, `ROOM_TYPE_MISMATCH`, `ROOM_RESERVED_FOR_LARGE_CLASSES`, `ROOM_POLICY_UNDEFINED`) |
| `slots[]` | Start times on `date` inside opening hours, every 15 minutes, plus the class's own current start: `start`, `end` (campus `HH:MM`), `starts_at` (UTC), `free_room_ids` (rooms where the whole class fits at that start). Past starts have no free rooms. Weekends and closed dates have no slots |
| `selected` | Only with `start`: `start`, `end`, `starts_at`, `ends_at`, `time_issues[]`, `available_room_ids[]`, `room_issues{room_id: issues[]}` |

`time_issues` are problems with the time itself, whatever the room. When there are any, `available_room_ids` is empty. The codes are:
- `IN_PAST`
- `OUTSIDE_TEACHING_HOURS`
- `LECTURER_CONFLICT`
- `STUDENT_CONFLICT`
- `START_NOT_WHOLE_MINUTE`
- `OUTSIDE_HORIZON`

`room_issues` explains each unavailable room: `ROOM_CONFLICT` (booked within the gap), plus the suitability codes above. Each issue is `{code, detail}` with a readable `detail`.

Example: `GET /api/admin/timetable/<id>/availability?date=2026-11-18&start=10:00`:
```json
{
  "date": "2026-11-18", "timezone": "Asia/Kuala_Lumpur", "duration_minutes": 90, "student_count": 32,
  "status": "scheduled", "step_minutes": 15,
  "rooms": [{"id": "…", "name": "R1", "suitable": true, "issues": []}, {"name": "LAB", "suitable": false,
             "issues": [{"code": "ROOM_TYPE_MISMATCH", "detail": "…"}]}],
  "slots": [{"start": "08:30", "end": "10:00", "starts_at": "2026-11-18T00:30:00Z", "free_room_ids": ["…"]}],
  "selected": {"start": "10:00", "end": "11:30", "time_issues": [], "available_room_ids": ["<R2>"],
               "room_issues": {"<R1>": [{"code": "ROOM_CONFLICT", "detail": "…"}]}}
}
```

Errors:
- `404 CLASS_NOT_FOUND`
- `409 CLASS_NOT_ACTIVE` / `CLASS_STARTED`
- `422` for an invalid `date`, `start` (must be `HH:MM`) or `session_id`
- `502` / `503` / `504` for database problems (`DATABASE_*`, or a `SchedulingDataError` code)

## `POST …/reschedule`

Body (extra fields rejected):

| Field | Meaning |
| --- | --- |
| `expected_starts_at`, `expected_room_id` | The class's start and room as the page loaded them (aware timestamp, UUID) |
| `starts_at` | New start, with a timezone offset, whole minutes |
| `room_id` | New room |
| `reason` | **Optional** (since 12 November 2026, the user's decision): up to 500 characters, kept in `schedule_changes`. Missing, `null` or blank is recorded as `"No reason given"`, because `admin_reschedule_class` requires a non-empty reason; this avoids a new migration |

Steps:
1. Validate the body.
2. Reload the class. It must be active and not started; its start and room must still equal the expected values (else `409 CLASS_CHANGED`); and the move must actually change something (else `422 NO_CHANGE`).
3. Re-check the new start and room against fresh data with the validator. Any problem → `409 SLOT_UNAVAILABLE` with `issues[]`, and **nothing is written**.
4. Call `public.admin_reschedule_class` with the **admin's own access token**, so the database sees the admin (`auth.uid()`). In one transaction the function:
   - takes the timetable advisory lock;
   - checks the class is unchanged;
   - re-checks room type, capacity and clashes;
   - updates the class and sets `status = 'rescheduled'`;
   - writes a `schedule_changes` `reschedule` row with the reason and the old and new values.

Response `200`: `{"status": "RESCHEDULED", "session_id", "starts_at", "ends_at", "room_id"}`. The change is visible at once to the class's students, its lecturer and administrators.

Other errors: `403 ORIGIN_NOT_ALLOWED` (another site's browser `Origin`), `422` for an invalid body (missing timezone, reason over 500 characters, extra fields), `422 START_NOT_WHOLE_MINUTE`.

Database errors are mapped without provider text:

| Database code | Response |
| --- | --- |
| `23P01` | `409 SLOT_TAKEN` (booked by someone else meanwhile) |
| `40001` | `409 CLASS_CHANGED` |
| `22023` | `409 MOVE_REJECTED` |
| `P0002` | `404 CLASS_NOT_FOUND` |
| `42501` | `403 ADMIN_REQUIRED` |
| `PGRST202` / `42883` / `42703` | `503 MIGRATION_MISSING` |
| Timeout | `504 RESCHEDULE_OUTCOME_UNKNOWN` |
| Anything else | `502 DATABASE_REJECTED` |

**Requires** migrations `202611110001_admin_timetable` and `202611120003_admin_reschedule_fixes` on the database ([migration guide](hosted-migrations.md)).

## Limits

- **Gap race:** the engine check (step 3) and the database function (step 4) are separate. The function re-checks overlaps under the lock, but not the 15-minute gap or opening hours. A booking created elsewhere between the two steps could therefore leave a gap shorter than 15 minutes.
- **Readers:** the availability answer is a snapshot; the save re-checks everything.
- **Time grid:** the 15-minute start grid is only what the page offers. The `POST` accepts any whole minute.
- **Older endpoints:** `PUT /api/admin/timetable/{id}` (admin API) still calls the database function directly, without the engine check. The lecturer page's `PATCH /api/lecturers/{id}/sessions/{id}` still uses its own checks ([review](lecturer-reschedule-review.md)). Both should move to this path.
- **Notifications:** none are sent; people see the change in their timetables.

## Verification (12 November 2026)

- `test_admin_reschedule.py`: **28 passed**. A fake PostgREST feeds the real loader, validator and candidate generator. The tests cover:
  - room explanations, the time grid and opening hours;
  - the gap before and after a booking;
  - lecturer, cross-intake student and meeting clashes;
  - the class's own time staying free, closed weekends, and moving to another week;
  - not found, cancelled, started and invalid input;
  - access control;
  - a valid move calling the database function with the admin's token and the expected values;
  - invalid moves never reaching the database;
  - database error mapping without provider text.
- **Browser walkthrough** in headless Edge against the real backend on synthetic data with a fake database function (no Supabase): select, double-click, choosing a day and time, room greying, Save with confirmation, Cancel with confirmation, and the calendar updating.
- **Not run against hosted Supabase.**
