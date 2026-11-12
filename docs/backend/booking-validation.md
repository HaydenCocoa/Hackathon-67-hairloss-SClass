# Step 5 — Standalone class booking validation

Date: 10 November 2026 (Asia/Kuala_Lumpur).

Status: complete and verified locally. No new migration or hosted database change is required for this milestone.

## Accepted rules and design

**Changed 12 November 2026 (step 8, [timetable quality](timetable-quality.md)):** starts are whole minutes, a compulsory 15-minute gap separates bookings that share a room, lecturer or student, and auditoriums are used only when no other permitted room can seat the class. Older statements below about microsecond precision, no buffers or adjacent bookings are superseded.

The user confirmed the initial system-owned room policy during this task:

| Teaching type | Allowed room types |
| --- | --- |
| Lecture | Classroom, auditorium |
| Tutorial | Classroom, lab |
| Lab | Classroom, lab |
| Others | Requires an explicit configured mapping; initially empty |

Store this mapping under `scheduling.room_compatibility` in `Config/config.json`. Do not infer compatibility from the removed section-level `required_room_type`. Missing/empty mappings reject proposals explicitly. Startup validation rejects unknown course/room type names.

The loader copies these rules into the immutable snapshot and its content fingerprint. Validation uses that captured policy, roster, calendar, and booking data. No additional database call or write is needed to evaluate a proposal.

The validator accepts an occurrence UUID, aware start timestamp, room UUID, and schedule/reschedule mode. It derives the end time from the occurrence's course duration; the caller cannot override lecturer, roster, duration, or arbitrary conflict exclusions. Reschedule mode excludes only the selected occurrence's matching original class booking. Cancelled demand must be explicitly reopened first.

Check full duration against the selected week's horizon and one configured opening window. No preset start slots, lunch exclusions, mandatory breaks, or travel buffers apply. Intervals are half-open, so adjacent bookings do not overlap.

Check active room, capacity against unique student count, configured room compatibility, and lecturer/student/room conflicts across fixed classes/reservations and meetings. Online meetings block their lecturer/attendees but not a room. Return applicable structured issues with booking references and counts rather than exposing student UUIDs in rejection messages.

This is a pure internal validation result, not authorization, a reservation, or a committed booking. A target outside the captured week is rejected; step 11 must prepare a proper target-week context for cross-week moves. Concurrent new proposals must still be modeled together by later generation, and later commits must revalidate current data.

## Configuration

```json
"room_compatibility": {
  "lecture": ["classroom", "auditorium"],
  "tutorial": ["classroom", "lab"],
  "lab": ["classroom", "lab"],
  "others": []
}
```

Place this under `scheduling` in `Config/config.json` and restart the backend after editing. Supported course/room names are typed and validated. There is no silent fallback when a rule is missing or empty. The legacy `required_room_type`, if present in an older database view, does not constrain this confirmed policy.

## Internal usage and result

After obtaining a snapshot with `load_scheduling_snapshot`, validate a proposal:

```python
from backend.app.scheduling.validator import BookingProposal, BookingValidator

validator = BookingValidator(snapshot)
proposal = BookingProposal(
    occurrence_id=occurrence_id,
    starts_at="2026-11-09T09:17:00+08:00",
    room_id=room_id,
)
result = validator.validate(proposal)
```

Use existing UUIDs from the scheduling input for `occurrence_id` and `room_id`. `result.valid` indicates success, `result.ends_at` is derived from duration, `result.issues` contains rejection details, and `result.snapshot_revision` identifies the captured data/policy. `validate_booking(snapshot, proposal)` is a convenience function for one call. Reuse a `BookingValidator` when checking many candidates against one snapshot.

Set `mode="reschedule"` only for an occurrence with a scheduled original booking in the snapshot. A normal proposal for a booked lesson returns `ALREADY_SCHEDULED`. Cancelled demand returns `OCCURRENCE_CANCELLED`; after explicit reopening, pending make-up demand may be placed with normal schedule mode.

Input models reject malformed UUIDs, timezone-naive starts, unknown modes, extra duration/lecturer/roster fields, and arbitrary exclusions with Pydantic validation errors before rule evaluation. Timestamps normalize to UTC without rounding.

### Rejection categories

| Codes | Meaning |
| --- | --- |
| `OCCURRENCE_NOT_FOUND`, `OCCURRENCE_CANCELLED` | Lesson is missing from this input or deliberately cancelled |
| `ALREADY_SCHEDULED`, `NOT_SCHEDULED`, `ORIGINAL_BOOKING_NOT_FOUND` | Requested operation does not match booking lifecycle/context |
| `INVALID_START_TIME`, `OUTSIDE_HORIZON`, `OUTSIDE_TEACHING_HOURS` | Duration cannot be represented, is outside the loaded week, or does not fit one opening window |
| `ROOM_NOT_FOUND`, `ROOM_INACTIVE`, `ROOM_TOO_SMALL` | Invalid room or insufficient seats for the unique roster |
| `ROOM_POLICY_UNDEFINED`, `ROOM_TYPE_MISMATCH` | Missing compatibility rule or unsuitable actual room type |
| `LECTURER_CONFLICT`, `STUDENT_CONFLICT`, `ROOM_CONFLICT` | Overlapping fixed class/reservation or meeting, or one closer than `min_gap_minutes` (15) |
| `START_NOT_WHOLE_MINUTE` | Start has seconds (since 12 November 2026) |
| `ROOM_RESERVED_FOR_LARGE_CLASSES` | An auditorium was proposed although another active, permitted room can seat the class (since 12 November 2026) |

Room and conflict checks collect applicable reasons together. Lifecycle/horizon failures return early because this snapshot cannot safely validate that operation. Conflict issues identify booking kind/UUID and student-conflict count where relevant; no student UUID list is returned in the result.

## Files and verification

| File | Change |
| --- | --- |
| `Config/config.json`, `backend/app/config.py` | Confirmed room mapping and typed configuration |
| `backend/app/scheduling/loader.py` | Captured immutable rules included in the input fingerprint |
| `backend/app/scheduling/validator.py` | Pure proposal validation and structured results |
| `backend/tests/test_booking_validator.py` | Policy, calendar boundaries, conflicts, lifecycle, exclusions, and input/result checks |
| `backend/tests/test_scheduling_loader.py` | Real PostgreSQL output through HTTP into the validator; policy fingerprint regression |

Results on 10 November 2026:

- Focused validator suite: **52 passed**. The initial restricted run emitted a cache-write warning; all assertions passed.
- Full backend suite: **148 passed, 1 skipped**, in 54.94 seconds, with one existing test-client deprecation warning. The skipped test requires the optional Postman simulation, which was not running.
- Loader integration uses the real local PostgreSQL function's output through a temporary HTTP provider, then verifies a valid placement and a student clash across different intakes. Captured room-policy changes affect the fingerprint.
- No SQL behavior changed in step 5; SQL suites were not rerun solely for this pure validation/configuration work. Prior database results remain historical evidence from step 4. The backend integration tests still execute the existing local PostgreSQL function.
- `git diff --check` and local documentation links passed.

All fixtures are synthetic local data. No meeting samples or deliberately impossible datasets were added to the hosted database. Existing meeting support is tested when present, while empty meetings remain valid input.

## Boundaries and next work

- Internal service only; no new frontend or public API route.
- Earlier prepared migrations remain prerequisites for loading live snapshots; step 5 adds no migration.
- Results use the captured horizon, resources, rosters, windows, and policy. Reload after data/config changes; a validation result does not lock resources against simultaneous requests.
- Cross-week cancel/reschedule orchestration, authenticated writes, and atomic booking/audit persistence remain future milestones.
- Step 6 now implements [candidate start ranges](candidate-generation.md), reusing shared lifecycle, room, and resource-blocker checks without preset start-time slots. Joint assignment remains step 7.
- Offering end dates and automatic holiday/semester-break feeds remain deferred.
