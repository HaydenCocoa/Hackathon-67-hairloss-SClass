# Step 8: timetable quality

Implemented and verified locally: 12 November 2026, branch `backend-enhancement`. **Not run against the hosted Supabase project.** This replaces the plan written earlier the same day.

Related: [CP-SAT solver](cp-sat-scheduling.md), [booking validation](booking-validation.md), [candidate ranges](candidate-generation.md), [preview API](schedule-preview-api.md), [backend record](agents.md), [checklist](../../task_hayden.md).

## Requirement

Make valid timetables comparable with meaningful measurements and let configured preferences influence generation: reduce student waiting time first, then lecturer gaps, then improve room use. Compulsory rules always win over preferences.

## Accepted decisions (12 November 2026)

| # | Topic | Decision |
| --- | --- | --- |
| Q1 | Start-time precision | **Whole minutes.** This changes the accepted rule "classes can start at any time" to "at any minute". It is not a fixed grid. |
| Q2 | Combining priorities | **Weighted sum** in one search: student idle 100, lecturer idle 10, room fit 1. |
| Q3 | Room utilization | **Compulsory:** auditoriums are used only for a class that no other permitted room can seat. **Preference:** among allowed rooms, fewer empty seats (room fit). |
| Q4 | Balance across the week | No extra rule; `longest_student_day_minutes` is reported. |
| Q5 | Time limit | `solver.max_time_seconds`, shared by both searches. 10 s at first; **raised to 120 s (2 minutes) by the user on 12 November 2026.** It must be greater than 0 (0 or unlimited is rejected at startup). |
| Q6 | Switching off | Config only (`quality.enabled`); no request option. |
| Q7 | Broken solver fixtures | Fixed first (test code only). |
| Q8 | Branch | Current branch, `backend-enhancement`. |
| New | Gap between classes | **Compulsory: 15 minutes** between two bookings that share a room, a lecturer or a student. Applies to new classes against each other and against existing classes and meetings, on both sides. Set by `min_gap_minutes`. |

Interpretations made during implementation (please confirm):

- The 15-minute gap applies to every shared resource (room, lecturer, student), including meetings, not only to students.
- "Other classroom cannot handle" is judged by **capacity, not availability**: if any active, permitted, non-auditorium room has enough seats, the auditorium is refused even when that room is busy at the time.

## Compulsory rules (always enforced)

Enforced in the shared `BookingValidator`, so candidate generation, the solver's post-check and the step 10 save recheck all agree:

| Rule | Reason code |
| --- | --- |
| Start on a whole minute | `START_NOT_WHOLE_MINUTE` |
| 15 minutes from any booking sharing the room / lecturer / students | `ROOM_CONFLICT` / `LECTURER_CONFLICT` / `STUDENT_CONFLICT` (detail mentions the gap) |
| Auditorium only when no other permitted room is large enough | `ROOM_RESERVED_FOR_LARGE_CLASSES` |

Candidate ranges widen every fixed blocker by the gap and are narrowed to whole-minute starts. In the solver, each new class occupies its room, lecturer and students for its duration plus the gap, so new classes also keep the gap between each other. `verify_placements` checks the gap independently.

The rules are captured in the snapshot (`min_gap_minutes`, `reserved_room_types`) and are part of its revision, so changing them makes existing previews stale.

**Not covered:** the lecturer reschedule endpoint (`PATCH /api/lecturers/{id}/sessions/{id}`) still writes without the validator (step 11), and existing bookings are not rechecked against the new rules.

## Preferences (rank valid timetables)

Two CP-SAT searches share the time limit:

1. Find any complete timetable satisfying every compulsory rule (as before).
2. Add the weighted objective, start from that timetable (solution hint), and improve it with the remaining time.

| Preference | What the solver minimizes |
| --- | --- |
| `student_idle` | For each student and teaching day: (last class end − first class start) − class minutes, including the student's fixed classes and meetings that day. Students with identical lessons and fixed days share variables and are weighted by their number. |
| `lecturer_idle` | The same per lecturer. |
| `room_fit` | Room capacity − students for each new class. |

Outcomes:

| Status | Meaning when preferences are on |
| --- | --- |
| `OPTIMAL` | Proven best timetable under the configured preferences |
| `FEASIBLE` | Valid; the search stopped before proving it is the best (common: the proof is often harder than finding the answer) |
| `FEASIBLE` + diagnostic `OPTIMIZATION_INCOMPLETE` | Valid, but not improved (less than 0.5 s left, or the improvement search found nothing); the first valid timetable is returned |

`quality_optimized` is `true` only when the second search produced the returned timetable. With `quality.enabled: false` (or all weights 0) the solver behaves as in step 7.

## Measurements (returned with every complete timetable)

`quality` in the result, computed from the final placements and the fixed bookings (independent of the solver). Only counts and minutes, no ids.

| Field | Meaning |
| --- | --- |
| `student_days` | Student-days containing at least one new class |
| `student_idle_minutes_total` / `_average` / `_max` | Waiting time between first and last class on those days (includes the compulsory gaps) |
| `longest_student_day_minutes` | Longest first-to-last span (Q4) |
| `lecturer_days`, `lecturer_idle_minutes_total` / `_max` | The same for lecturers |
| `empty_seats_total`, `seat_use_percent` | Over the new classes |
| `reserved_room_classes` | New classes placed in an auditorium |

`statistics` adds `optimization_ran`, `optimization_wall_time_seconds`, `objective_value` (weighted score, lower is better) and `best_bound`.

## Configuration (`Config/config.json`)

```json
"min_gap_minutes": 15,
"reserved_room_types": ["auditorium"],
"quality": {
  "enabled": true,
  "objectives": [
    {"name": "student_idle", "weight": 100},
    {"name": "lecturer_idle", "weight": 10},
    {"name": "room_fit", "weight": 1}
  ]
}
```

Validated at startup: gap 0–240, objective names unique and known, weights 0–1000.

## Example (synthetic MVP-sized week)

6 two-hour classes for the same 40 students, 3 lecturers, a 2-seat classroom, a 50-seat lab and a 500-seat auditorium:

| | Feasibility only | With preferences |
| --- | --- | --- |
| Student idle (total) | 2,400 min | **600 min** (only the compulsory 15-minute gaps) |
| Student-days | 80 | 200 |
| Longest student day | 8h 45m | 4h 15m |
| Lecturer idle | 15 min | 0 min |
| Status / time | `OPTIMAL`, 0.01 s | `FEASIBLE`, 10 s (best answer found, optimality not proven) |

## Code changes

| File | Change |
| --- | --- |
| `backend/app/config.py`, `Config/config.json` | `min_gap_minutes`, `reserved_room_types`, `QualitySettings` |
| `backend/app/scheduling/loader.py` | Snapshot captures the gap and reserved room types (part of the revision) |
| `backend/app/scheduling/validator.py` | Whole-minute starts, gap-widened blockers, auditorium rule, new codes |
| `backend/app/scheduling/candidates.py` | Whole-minute candidate ranges |
| `backend/app/scheduling/solver.py` | Minute time unit, gap in no-overlap intervals, two-phase search with the weighted objective, statistics, gap in `verify_placements` |
| `backend/app/scheduling/quality.py` (new) | `QualityReport`, `measure_quality` |
| `backend/app/scheduling/preview.py` | Passes quality settings; `quality_optimized` / `quality` are real values; OpenAPI text |
| `backend/app/scheduling/development/*` | Quality measures on the page; notice text |
| `backend/tests/test_booking_validator.py` | Stale `required_room_type` fixture field removed (revives 97 erroring tests) |
| `backend/tests/test_quality.py` (new), other tests | New rules and preferences; sub-minute tests updated to the whole-minute rule |

No database change.

## Verification (12 November 2026)

Local synthetic data only; the hosted Supabase project was not contacted.

- **Stale fixture fixed first (Q7):** removing `required_room_type` from the validator test fixture turned the 97 erroring validator/candidate/solver tests into running tests.
- **37 new tests passed** (`backend/tests/test_quality.py`):
  - Config values and validation.
  - The 15-minute gap: every shared resource, both sides, meetings, candidate ranges, two new classes, the independent check.
  - The auditorium rule: refused when a classroom fits; allowed when none does; a busy classroom does not unlock it; inactive or wrong-type rooms don't count.
  - Whole-minute starts.
  - Hand-computed measurements.
  - Preferences: closing gaps down to the 15-minute minimum; choosing the smallest fitting room.
  - Behaviour without preferences, with no time left, and when the improvement search fails.
- **Updated existing tests:** five sub-minute tests now follow the whole-minute rule. One loader test expects the 15-minute-earlier latest start. Preview and page tests expect `quality_optimized: true` and the measures.
- **Full backend suite: 335 passed, 10 failed, 0 errors, 1 skipped.** Before this work, on the same branch: 199 passed, the **same** 10 failures, 97 errors. The 10 are older loader/preview tests that still expect the removed RPC behaviour or the removed `required_room_type` field; they were not changed.
- **Scheduling page: 20 of 20 passed**, including a new quality-display test and both served-page tests against the synthetic QA service (port 8001, stopped afterwards). **Frontend auth:** 7 of 7.
- **Not verified:** a real week from hosted Supabase (model size and preview time), and the page in a real browser.

## Risks and limits

1. **Preview time.** With preferences on, a preview usually uses the whole time limit (now 120 s) because proving the best answer is hard even when it has been found. The admin waits that long, other previews and saves get `GENERATION_BUSY` meanwhile, and a closed browser does not stop the search. The development page is local-only, so hosted function limits do not apply to it today.
2. **Spreading across days.** Minimizing waiting time favours one class per day (see the example: student-days 80 → 200). That has no idle time but means more days on campus. A "fewer days" or "balanced days" preference is not implemented (Q4 deferred).
3. **Repeatability.** The improvement search stops on wall-clock time, so two runs can return different (equally valid) timetables.
4. **Capacity, not availability,** decides whether an auditorium is allowed. A large class may therefore be unschedulable if the only big-enough classroom is busy all week, even though the auditorium is free.
5. **Existing bookings** that break the new gap or auditorium rule are not changed or reported; only new placements must comply.
6. **Lecturer reschedule endpoint** bypasses all compulsory rules (step 11).
7. **Meaning of `OPTIMAL` changed** for callers that read the preview response.
