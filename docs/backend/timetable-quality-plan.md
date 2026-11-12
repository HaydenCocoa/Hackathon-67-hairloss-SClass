# Step 8: timetable quality — review and implementation plan

Written 12 November 2026. **Plan only. Nothing in this document is implemented.** The decisions below are open until the user answers them.

Related: [CP-SAT feasibility solver](cp-sat-scheduling.md), [preview API](schedule-preview-api.md), [backend record](agents.md), [checklist](../../task_hayden.md).

## Where step 8 stands

Step 8 was postponed by the user on 10 November 2026. The code confirms that none of it has been built:

| Checklist item (`task_hayden.md`) | Status in the code |
| --- | --- |
| Measure each student's idle minutes per day | Not built. No measurement code exists. |
| Reduce total student waiting time (first priority) | Not built. `solver.py` builds a feasibility model with **no objective**; any valid timetable is accepted. |
| Reduce lecturer gaps (second priority) | Not built. |
| Improve room utilization (third priority) | Not built. The solver picks any suitable room, so a 30-student class can take the 500-seat auditorium. |
| Priorities configurable | Not built. `Config/config.json` has only `solver.max_time_seconds`, `num_search_workers` and `random_seed`. |
| Compulsory rules stay mandatory | Already true for feasibility (no-overlap constraints, candidate ranges, `verify_placements` after every solve). Must stay true once objectives exist. |
| Return quality measurements | Not built. The preview returns `quality_optimized: false` and `quality: null`; the development page says optimization is postponed. |

What step 8 can build on (done in steps 4–7):

- Exact integer-microsecond times with no start-time grid, one interval per new class, and an optional interval per room choice.
- Fixed classes and meetings with their student ids in the snapshot, so a student's existing classes on a day are known (including other intakes).
- Opening windows per teaching day, room capacities and room-type rules.
- Students with identical lessons are already grouped to keep the model small.

**Test blocker found during this review:** `test_solver.py`, `test_candidates.py` and `test_booking_validator.py` error before running (part of the 95 pre-existing errors) because their fixture still passes the removed `required_room_type` field. Step 8 needs working solver tests, so this fixture must be fixed first (test code only).

## Proposed design

### 1. Measurement first (independent of the solver)

New `backend/app/scheduling/quality.py` with a pure-Python `measure_quality(snapshot, placements)`. It is computed from the final timetable, so it reports the truth even when the search stops early.

| Measure | Definition |
| --- | --- |
| Student idle minutes | For each student and each teaching day with at least one class: (last class end − first class start) − minutes in class. Includes the student's fixed classes and meetings that day. Reported as total, average per student-day and the worst student-day. |
| Lecturer idle minutes | The same, per lecturer, using classes and meetings. |
| Room fit | For each new class: room capacity − students. Reported as total empty seats and average seat use (%). |

Only the students, lecturers and rooms touched by the new classes are measured. Results are counts and minutes only, with no ids or names, so they are safe to return and log.

### 2. Objectives in the CP-SAT model

For each group of students with the same lessons (existing grouping, extended to include their fixed bookings per day), lecturer and teaching day:

- a "this class is on day d" boolean, because a class's possible starts can span several days;
- the first start and last end of that day as min/max over the present classes and fixed bookings;
- idle = span − class minutes, multiplied by the number of students in the group.

Room fit is linear: each room-choice boolean × (capacity − students).

The objective combines the three according to the configured priority (decision Q2). The feasibility solution is found first and passed as a hint, so an answer is still returned when the time runs out. `verify_placements` stays unchanged and runs on every result.

### 3. Configuration (`Config/config.json`)

```json
"quality": {
  "enabled": true,
  "objectives": [
    {"name": "student_idle", "weight": 100},
    {"name": "lecturer_idle", "weight": 10},
    {"name": "room_fit", "weight": 1}
  ]
}
```

Validated at startup like the existing settings. `enabled: false` gives today's behaviour.

### 4. API and page

- `quality_optimized` becomes `true` when an objective was used; `quality` returns the measures above, plus `objective_value` and `best_bound`.
- `OPTIMAL` then means "best possible under the configured preferences"; `FEASIBLE` means "valid, but the search stopped before proving it is the best". The documentation for `OPTIMAL` changes accordingly.
- The development page shows the measures and drops the "optimization is postponed" notice. Saving (step 10) is unchanged: it saves exactly what was previewed.

### 5. Files

| File | Change |
| --- | --- |
| `backend/tests/test_booking_validator.py` and shared fixtures | Remove `required_room_type` from the fixture (prerequisite) |
| `backend/app/scheduling/quality.py` (new) | Measurement and objective-building helpers |
| `backend/app/scheduling/solver.py` | Add the objective, the feasibility hint and objective statistics |
| `backend/app/config.py`, `Config/config.json` | `QualitySettings` |
| `backend/app/scheduling/preview.py` | `quality_optimized`, `quality` and OpenAPI text |
| `backend/app/scheduling/development/*` | Show quality measures |
| `backend/tests/test_quality.py` (new) | Hand-computed idle and room-fit cases, objective preferring compact timetables, weights changing the result, compulsory rules still enforced, time limit respected |
| Docs | New `timetable-quality.md` (replacing this plan), `cp-sat-scheduling.md`, `schedule-preview-api.md`, `agents.md`, `task_hayden.md` |

No database change is needed.

## Risks

1. **Slower previews.** A feasibility search stops at the first answer; an optimization search uses the whole time limit unless it proves the best answer. Every preview could take the full `max_time_seconds` (10 s today). On a hosted deployment such as Vercel this counts against the function time limit.
2. **Model size.** Per-day first/last tracking adds booleans and min/max constraints for every student group, lecturer and day. Cross-intake students create more distinct groups. Large weeks may end as `FEASIBLE` rather than `OPTIMAL`.
3. **Microsecond times.** Objectives over microsecond values make it harder for CP-SAT to prove optimality (see Q1).
4. **Unbalanced weeks.** Minimizing idle time alone can pack many classes into one day with no break. The accepted rules say there are no mandatory breaks, but the result may be unpleasant for students (see Q4).
5. **Repeatability.** With a wall-clock time limit, two runs on different machines can return different (equally valid) timetables. The preview revision is unaffected, but the same week may look different each time.
6. **Fixed classes cannot move.** Gaps caused by existing bookings or other intakes' classes count in the measure, but the solver can only work around them.
7. **Meaning of `OPTIMAL` changes** for anyone already reading the preview response.

## Decisions needed from you

| # | Decision | Options | Recommendation |
| --- | --- | --- | --- |
| Q1 | Time precision for optimization | (a) keep exact microsecond starts; (b) whole-minute starts. (b) changes the accepted rule "classes can start at any time" to "at any minute"; it is not a fixed grid. | **(b) whole minutes**: smaller model, faster proofs, invisible to users. Needs your explicit approval because it changes an accepted rule. |
| Q2 | How priorities combine | (a) weighted sum (one solve, weights in config); (b) strict order (solve for student idle, lock it, then lecturer idle, then room fit: three solves sharing the time limit) | **(a) weighted sum** with weights 100 / 10 / 1: one solve, simpler and faster. Strict order is exact but slower. |
| Q3 | Meaning of "room utilization" | (a) fewest empty seats (best-fit room); (b) fewest different rooms used; (c) keep a group in the same room | **(a) fewest empty seats**: matches the auditorium example, cheap to model. |
| Q4 | Balance across the week | (a) no extra rule; (b) a soft penalty for very long days; (c) a hard cap on teaching minutes per student-day | **(a) for now**, measure the longest day in `quality`, and revisit after seeing results. |
| Q5 | Time limit for optimized previews | Keep 10 s, or raise it | **Keep 10 s** (configurable); fine for one intake locally. Recheck before hosting. |
| Q6 | Can the admin turn optimization off per preview? | (a) config only; (b) also an `optimize` flag on the request | **(a) config only**: smallest API change. |
| Q7 | Fix the broken solver test fixtures first | Yes / no | **Yes** (test code only); needed for meaningful step 8 tests. |
| Q8 | Branch | Current `backend-enhancement`, or a new branch from `main` | Your choice; the save audit is on `backend-enhancement`. |

## Completion target (unchanged)

Valid timetables can be compared with meaningful measures, such as total student idle minutes, and the configured preferences change what is generated, while every compulsory rule stays enforced.
