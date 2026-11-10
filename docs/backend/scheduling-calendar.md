# Step 1 — Configurable teaching calendar

Date: 10 November 2026 (Asia/Kuala_Lumpur).

## Accepted requirements and decisions

The user requested configurable teaching days and opening hours and removed the requirement for permitted start-time slots and mandatory breaks. Their initial hours, "Monday - Friday 830-600", are interpreted as Monday–Friday, 08:30–18:00.

- Keep calendar rules in the existing tracked `Config/config.json`, loaded at startup. Restart the backend after changes.
- Use a weekday-to-hours mapping so teaching days and different daily hours are configurable together. An omitted weekday is closed.
- Use `Asia/Kuala_Lumpur` initially, with validation for available IANA timezone names.
- Support explicit full-day closures, initially empty, so holidays can be configured without changing code. No external holiday calendar is used.
- Allow arbitrary start times, including seconds and fractional seconds in the calendar check. Do not round or snap class starts to fixed slots.
- Require the entire positive-duration interval to fit within one same-day opening window. Starting exactly at opening and ending exactly at closing are allowed.
- Apply no mandatory breaks, lunch exclusion, or travel buffer.
- Require timezone-aware timestamps. Convert to the configured timezone to determine the teaching date; compare instants in UTC.
- Keep personal availability preferences outside this initial milestone.
- Treat calendar eligibility as one component of availability. Later validation must also check lecturers, students, rooms, meetings, and reservations.

## Configuration

```json
"scheduling": {
  "timezone": "Asia/Kuala_Lumpur",
  "opening_hours": {
    "monday": {"opens_at": "08:30", "closes_at": "18:00"},
    "tuesday": {"opens_at": "08:30", "closes_at": "18:00"},
    "wednesday": {"opens_at": "08:30", "closes_at": "18:00"},
    "thursday": {"opens_at": "08:30", "closes_at": "18:00"},
    "friday": {"opens_at": "08:30", "closes_at": "18:00"}
  },
  "closed_dates": []
}
```

Supported weekday keys are lowercase `monday` through `sunday`. At least one opening day is required. Times use strict 24-hour `HH:MM` format, with opening before closing on the same day. Overnight windows and `24:00` notation are not supported by this initial configuration model. Closure dates use `YYYY-MM-DD`; an explicit closure overrides ordinary opening hours.

To change one day's hours, edit its `opens_at` and `closes_at`. To enable Saturday, add a `saturday` entry. To close a weekday, remove its entry. Add dates to `closed_dates` for specific closures.

## Implementation

| File | Change |
| --- | --- |
| `Config/config.json` | Add initial scheduling settings |
| `backend/app/config.py` | Add `OpeningHours`, `SchedulingSettings`, weekday validation, timezone validation, and required scheduling settings |
| `backend/app/scheduling/calendar.py` | Add reusable `TeachingCalendar` |
| `backend/app/scheduling/__init__.py` | Establish the scheduling package |
| `backend/app/main.py` | Initialize the calendar as `app.state.teaching_calendar` |
| `backend/requirements.txt` | Add `tzdata>=2024.1` for IANA timezone support on Windows and other environments without system timezone data |
| `backend/tests/test_scheduling_calendar.py` | Verify interval boundaries, arbitrary starts, closures, timezones, configurable weekdays, and invalid settings |
| `backend/tests/test_app.py` | Verify app startup uses configured calendar hours |

### Internal interface

`TeachingCalendar(settings: SchedulingSettings)` takes a copy of the startup calendar configuration.

`opening_window(day: date) -> tuple[datetime, datetime] | None` returns the configured local opening and closing timestamps, or `None` on closed dates or omitted weekdays.

`is_within_opening_hours(starts_at: datetime, ends_at: datetime) -> bool` checks that the complete interval fits within that day's opening window. Zero/negative durations, closed days, starts before opening, ends after closing, and intervals crossing into another day return `False`. Missing timezone offsets raise `ValueError` rather than being interpreted silently.

### Examples under the initial configuration

| Class interval (Kuala Lumpur time) | Calendar result |
| --- | --- |
| Monday 08:30–18:00 | Allowed |
| Monday 09:17–10:47 | Allowed |
| Monday 12:00–13:30 | Allowed; no lunch-break rule |
| Monday 08:29–10:00 | Rejected; starts before opening |
| Monday 17:00–18:30 | Rejected; ends after closing |
| Saturday 09:00–10:00 | Rejected; no Saturday hours configured |
| Monday 10:00–11:00 on an explicit closed date | Rejected |

## Verification

Automated checks cover full-window boundaries, seconds and fractional seconds, unrestricted midday starts, UTC-to-local conversion, closed weekdays, configurable weekend hours, closure overrides, nonpositive intervals, overnight intervals, timestamps without offsets, and invalid startup settings. The startup integration check changes a configured opening time and verifies that the app uses it.

Run from the project root:

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest backend/tests -q
```

Verification results on 10 November 2026:

- Focused run of `backend/tests/test_scheduling_calendar.py` and `test_startup_uses_configured_teaching_calendar`: **29 passed**.
- Full `backend/tests` suite: **43 passed, 1 skipped**, in 10.29 seconds. The skipped check requires an optional Postman simulation, which was not running.
- One existing test-client deprecation warning recommends a future `httpx2` migration; no unrelated dependency migration was attempted.
- `git diff --check` passed.

The restricted integration-test run stalled while Windows asyncio created a local socket pair, before request handling. Stopped the stalled runs and reran with approved local networking. The full suite passed using a local Supabase stand-in; this does not establish hosted Supabase connectivity.

Environment note: the initial dependency download could not resolve the package host under restricted network access. The approved retry installed `tzdata` 2026.6 in the local virtual environment.

**Status: step 1 complete.** No further user input is required for this milestone.

## Boundaries and next work

This step adds no scheduling API, generated timetable, database write, schema migration, conflict detection, reservation persistence, or CP-SAT dependency. Those remain later development steps.

Next is step 2: model required teaching occurrences and their identities, weekly requirements, cancellation state, and rescheduling behavior. Later solver work must explicitly choose time precision while preserving the user's requirement against preset teaching slots.

References: [Python timezone data requirements](https://docs.python.org/3/library/zoneinfo.html), [Pydantic validation](https://docs.pydantic.dev/latest/concepts/validators/).
