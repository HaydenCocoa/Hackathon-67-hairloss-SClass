# Step 6 — Feasible start-time ranges

Date: 10 November 2026 (Asia/Kuala_Lumpur).

Status: complete and verified locally. No new migration or hosted database change is needed for step 6.

## Design and decisions

The user requested step 6 after completing standalone validation. Candidate generation must preserve unrestricted starts, exact class duration, configured course-to-room policy, and all fixed resource conflicts.

Return room-specific closed start-time ranges, not a discretized list of preset slots. A two-hour class with uninterrupted availability from 08:30 to 12:00 can start anywhere in `[08:30, 10:00]`, including the endpoints. Times retain Python datetime's microsecond precision. A free interval exactly as long as the class yields a single valid start with equal earliest/latest values.

Refactored step 5's validator into shared lifecycle, room-eligibility, and resource-blocker methods. Its normal validation entry point uses the same methods, so candidate generation does not maintain a second compatibility, roster-conflict, cancellation, or reschedule-exclusion policy.

For each suitable room, collect all relevant fixed booking intervals, clip them to each opening window, merge overlapping/adjacent occupied intervals, and subtract them. A free gap `[a, b)` permits starts `[a, b - duration]` when the gap is at least the full class duration. No free time is joined across distinct teaching days/windows. No range is rounded or truncated to a limited list of suggestions.

The output is per occurrence against the captured week's fixed bookings. Candidates for multiple new lessons can conflict with one another; CP-SAT in step 7 must choose their joint assignment. Generation creates no bookings, reservations, authorization, or hosted sample data.

## Verification plan

Check complete free windows, exact-fit points, room filtering, lecturer/student/room blockers, merged and clipped intervals, fractional-second boundaries, cancelled bookings, same-class rescheduling exclusions, weekly pending selection, empty/failing results, deterministic output, and agreement with the standalone validator at boundaries and sampled interior points. Also exercise generation through the existing local PostgreSQL-output/HTTP loader integration path. No hosted meeting or intentionally impossible dataset is required.

## Internal usage

Load a snapshot using step 4, then generate one occurrence's possibilities:

```python
from backend.app.scheduling.candidates import CandidateGenerator

generator = CandidateGenerator(snapshot)
result = generator.generate(occurrence_id)
```

`result.ranges` is a tuple of immutable `CandidateRange` records:

| Field | Meaning |
| --- | --- |
| `occurrence_id`, `room_id` | Lesson and room identities |
| `earliest_start` | First valid start in the range, inclusive |
| `latest_start` | Last valid start in the range, inclusive |
| `duration_minutes` | Exact course duration; no rounding |

`range.contains(aware_datetime)` tests membership without snapping the start time. Boundaries and output instants are UTC. Convert using the snapshot timezone when displaying local times. `has_candidates` is true when at least one range exists; `diagnostics` explains excluded choices. Results also carry `snapshot_revision`, `horizon_starts_at`, and `horizon_ends_at`.

Use `generator.generate(occurrence_id, mode="reschedule")` for a scheduled occurrence already represented in this snapshot. It shares step 5's original-booking exclusion. Cancelled demand must be explicitly reopened; generation does not alter lifecycle state. Cross-week moves still require proper target-week context in step 11.

For all pending lessons:

```python
weekly = generator.generate_pending()
blocked = weekly.blocked_occurrence_ids
```

`weekly.occurrences` contains one result per pending occurrence, sorted by UUID. Already scheduled/cancelled demand is omitted from this default batch. `generate_candidates(snapshot, occurrence_id)` and `generate_weekly_candidates(snapshot)` provide one-call convenience functions. An empty batch means no pending input; it is not a generated timetable.

## No-candidate diagnostics

Lifecycle and static-room reasons reuse the validator's `BookingIssue` codes and details. Candidate-specific summaries are:

| Code | Meaning within this captured horizon |
| --- | --- |
| `NO_TEACHING_WINDOWS` | No effective opening window overlaps the selected week |
| `DURATION_EXCEEDS_OPENING_WINDOWS` | No single opening window can hold the full duration |
| `NO_ROOMS` | Room inventory is absent |
| `NO_SUITABLE_ROOMS` | No room passes activity, capacity, and configured compatibility checks |
| `NO_VALID_START_RANGE` | Suitable rooms exist, but fixed bookings leave no sufficiently long uninterrupted gap |

Room-specific diagnostics include room UUIDs. Supporting blockers include booking UUID/kind and student-conflict counts, without listing student UUIDs. Duplicate supporting reasons are collapsed per room/booking/kind/code. These are useful blockers, not a computed minimum explanation of impossibility.

Diagnostics may describe rejected rooms even when `has_candidates` is true. Use the presence of ranges to determine whether an occurrence has options. Failure is limited to the selected horizon and captured policy/data; it is not a claim that another week or changed input could never work.

## Shared validator implementation

Step 5's validator now exposes shared helpers used by both validation and generation:

- `get_requirement`: retrieve the captured immutable lesson.
- `occurrence_issues`: validate scheduling/rescheduling lifecycle.
- `room_issues`: validate room identity/activity/capacity/policy without selecting a start.
- `blocking_intervals`: resolve only resource-relevant fixed bookings and the same original-class exclusion. Callers first check `occurrence_issues`.

The regular `validate` entry point still checks horizon and opening-window containment, and now consumes the shared blockers. No extra database request is made. This refactor avoids duplicated resource policies between candidate generation and direct booking validation.

## Verification results

- **24 candidate cases passed**, including merged/nested/adjacent occupancy, exact-fit points, subsecond boundaries, complete room-specific ranges, metadata/room policy filtering, cancellation/reschedule behavior, diagnostics, and weekly independence.
- **76 combined candidate/validator cases passed**; all existing validator checks remain passing after refactoring.
- **172 full backend tests passed, 1 skipped**, in 54.61 seconds. The skipped test needs the optional Postman simulation; one existing test-client deprecation warning remains.
- Boundary and interior-point comparisons match range membership to direct validator decisions across rooms and multiple resource blockers. The test sampling is verification only; the implementation imposes no sampling grid.
- The integration path uses actual local PostgreSQL function output served over a temporary HTTP provider, then loads, validates, and generates candidates. It verifies the shared-student booking trims the Monday latest start correctly and every produced range endpoint passes validation. Compatibility after removal of the legacy room field is exercised too.
- No SQL source changed, so prior database-suite results were not rerun or reported as new evidence. No live Supabase call or hosted data change occurred.
- `git diff --check` and local documentation links passed.

Run with the existing project Python environment:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_candidates.py backend/tests/test_booking_validator.py -q
.\.venv\Scripts\python.exe -m pytest backend/tests -q
```

This workspace used the previously documented ignored `.python-tools/runtime/python.exe` for executed checks because the original virtual environment still references a missing base interpreter. The full loader integration requires existing Node/PGlite local test tooling, which was available.

## Next milestone

Step 7 now implements [joint CP-SAT generation](cp-sat-scheduling.md) using these ranges with exact integer-microsecond time. Candidate ranges alone encode validity against fixed data; the joint solver also enforces clashes between new lessons. Quality objectives, authorization, and transactional commits remain later work. No booking/reservation is created by candidate generation.
