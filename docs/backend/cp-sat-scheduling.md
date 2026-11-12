# Step 7 — Joint CP-SAT timetable generation

Date: 10 November 2026 (Asia/Kuala_Lumpur).

Status: complete and verified locally. No new SQL migration or hosted data change is needed for step 7.

## Design decisions

**Changed 12 November 2026 (step 8, [timetable quality](timetable-quality.md)):** time is encoded in whole minutes (not microseconds); each new class occupies its resources for its duration plus the compulsory 15-minute gap; with preferences on, a second search minimizes the weighted student idle, lecturer idle and room-fit objective, starting from the first valid timetable. Statements below about microsecond time and feasibility-only solving describe step 7.

- Generate one room/start assignment for every pending occurrence in the captured week. Existing scheduled classes, reservations, meetings, and cancelled demand are not changed.
- Generate candidate ranges internally from the trusted snapshot. Do not accept externally altered candidate domains or silently omit a lesson with no ranges.
- Encode time as integer microseconds relative to the week's UTC horizon start. This exactly preserves Python/PostgreSQL timestamp precision without preset teaching slots or float timestamp conversion.
- Give each new lesson one mandatory interval and exactly one optional room choice. Restrict its start to that room's union of complete candidate ranges. Apply no-overlap constraints for new classes sharing a lecturer, room, or actual student identity.
- Fixed bookings already block candidate ranges through the shared validator. Do not force pre-existing legacy bookings to become mutually conflict-free as an unrelated condition of scheduling new classes.
- Use a configurable search-time limit, worker count, and random seed. Solve for feasibility only; step 8 will add timetable quality objectives.
- Distinguish successful solver outcomes from proven infeasibility, incomplete search, invalid models, and an explicitly empty pending week. Never return partial placements as a complete timetable.
- Verify extracted assignments independently against the validator and against one another before returning them. Results are drafts tied to an input revision, not authorized or committed bookings.

References: [CP-SAT status definitions](https://developers.google.com/optimization/cp/cp_solver), [interval and optional-interval scheduling](https://github.com/google/or-tools/blob/stable/ortools/sat/docs/scheduling.md), [search limits](https://developers.google.com/optimization/cp/cp_tasks).

## Setup and configuration

OR-Tools is declared as `ortools>=9.14,<10` in `backend/requirements.txt`. Install the updated requirements in the backend environment before importing the solver:

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.txt
```

The tested version is **9.15.6755** on CPython 3.12.10, Windows x64. This workspace uses the previously documented ignored `.python-tools/runtime/python.exe` with the existing project packages because the original virtual environment references a missing base interpreter. OR-Tools and its dependencies were installed locally. Approved verification could read/run the new package; the restricted execution context could not read its package directory. No global installation or Python configuration change was made.

Configure `scheduling.solver` in `Config/config.json`:

```json
"solver": {
  "max_time_seconds": 60,
  "num_search_workers": 1,
  "random_seed": 0
}
```

The time limit must be positive and finite; worker count is an integer from 1 to 32; seed is a nonnegative signed-32-bit integer. Defaults favor a simple reproducible single-worker setup. Search options are recorded in results. The limit applies to CP-SAT search; data loading, candidate/model construction, and independent validation are additional work measured by total elapsed time.

## Internal usage

After loading the snapshot through step 4:

```python
from backend.app.scheduling.solver import solve_weekly_schedule

result = solve_weekly_schedule(snapshot, settings.scheduling.solver)
if result.has_solution:
    assignments = result.placements
else:
    reasons = result.diagnostics
```

Pass the configured `SolverSettings` explicitly. Omitting it uses the model's defaults rather than rereading global configuration. The function is synchronous CPU work; a future async FastAPI endpoint should dispatch it to a worker/thread/job rather than blocking its event loop. No new endpoint is added here.

### Output

`ScheduleResult` is immutable and includes:

- `status`, `has_solution`, and `required_count`.
- `snapshot_revision`, selected `week_start`, and campus `timezone`.
- `placements`: one immutable `ClassPlacement` per pending lesson on success, with occurrence/section/lecturer/room IDs, aware UTC start/end, and unique student count. Student UUID lists and names are not included.
- `candidate_failures`: blocked occurrence results with existing step 6 diagnostics when candidate preparation proves a lesson cannot be placed.
- `diagnostics`: concise result-level reasons.
- `statistics`: whether search ran, time/worker/seed options, total elapsed time, solver wall time, branches, and conflicts.

Only pending occurrences receive new assignments. Existing scheduled lessons remain fixed in the snapshot and are not duplicated in `placements`. A successful result covers all pending occurrences exactly once; every unsuccessful result has an empty placements tuple.

| Status | Interpretation |
| --- | --- |
| `OPTIMAL` | Without preferences: the feasibility model is solved. With preferences (since 12 November 2026): proven best timetable under the configured weights |
| `FEASIBLE` | A complete valid assignment is available |
| `INFEASIBLE` | Empty candidate domains or solver proof establish no complete assignment under this captured input |
| `UNKNOWN` | Search ended without a solution/proof; this does not establish impossibility |
| `MODEL_INVALID` | The generated model failed validation or the solver rejected it; treat as an engine/configuration issue |
| `NO_PENDING_REQUIREMENTS` | Explicit empty pending input; no solver was run and no timetable is claimed |

`statistics.solver_ran` distinguishes an early no-candidate conclusion from a joint solver proof. If every lesson has individual candidates but they compete for the same limited resources, the solver can still return joint `INFEASIBLE`. No minimum unsatisfiable subset is computed.

## Modeling and verification details

The model gives each pending lesson a start variable with a union of candidate domains, a fixed integer-microsecond duration, an end variable, and a mandatory interval. Each eligible room has one Boolean choice and an optional interval. Exactly one room is selected, and its Boolean enforces the room-specific start domain. Room no-overlap uses these optional intervals; lecturer/student no-overlap uses mandatory class intervals.

Multiple students attending identical lesson sets need only one identical no-overlap constraint. The grouping uses actual UUID memberships, preserving cross-intake clashes. Different groups without shared students can still run in parallel if lecturers and rooms permit it.

Fixed data is already excluded by complete candidate ranges. This keeps existing records fixed while avoiding an unrelated requirement that old bookings become mutually valid. The existing booking validator checks every extracted assignment again, including calendar, roster, room policy/capacity, and fixed blockers. A separate overlap scan checks generated assignments against one another. `ScheduleVerificationError` prevents publication if extraction or verification disagrees with the model.

Time offsets use integer timedelta division, not floating-point Unix timestamps. Within a week, microsecond offsets are safely inside CP-SAT's integer range. No room domain or start range is sampled, rounded, or truncated to a shortlist. Search-time limits can still leave the model unresolved.

## Files and executed verification

| File | Purpose |
| --- | --- |
| `backend/app/scheduling/solver.py` | Joint CP-SAT model, extraction, independent verification, immutable output |
| `backend/app/config.py`, `Config/config.json` | Validated search options |
| `backend/requirements.txt` | OR-Tools dependency |
| `backend/tests/test_solver.py` | Actual solver outcomes and scheduling/integrity cases |
| `backend/tests/test_scheduling_loader.py` | Real local PostgreSQL output over HTTP through complete generation |

Results on 10 November 2026:

- **29 focused solver cases passed**.
- **201 full backend tests passed, 1 skipped**, in 59.27 seconds. The skipped test needs the optional Postman simulation; one existing test-client deprecation warning remains.
- Genuine solver tests cover room/lecturer/student joint infeasibility despite individual candidates, parallel independent lessons, adjacent shared-resource classes, scarce-room choice, conditional room domains, disconnected windows, exact microsecond starts, existing-booking preservation, complete-only output, and an actual nanosecond-scale search budget yielding `UNKNOWN`.
- A six-component week for 40 shared students over five teaching days is solved with all six assignments and no overlap for that shared roster.
- `FEASIBLE` branch coverage relabels an actually solved valid model; model-invalid and validator-disagreement branches are fault-injected. These checks verify response safety without claiming those injected failures arose naturally.
- The integration chain uses real local PostgreSQL function output over a temporary HTTP provider, including the database variant without the legacy room field. The returned schedule is verified and makes no additional database requests. This is not a live Supabase or full PostgREST-server test.
- No SQL behavior changed, so existing SQL suites were not rerun solely for this pure computation/dependency addition. No hosted migration, sample insertion, or booking write was performed.
- `git diff --check` and local documentation links passed.

Run with a working project Python environment:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_solver.py -q
.\.venv\Scripts\python.exe -m pytest backend/tests -q
```

The full integration suite also requires the previously established local Node/PGlite tooling. It was present during verification. Postman CLI remains unavailable; no simulation was published or deployed for this task.

## Remaining work

Step 8's quality objectives were postponed on 10 November 2026 and implemented on 12 November 2026 ([timetable quality](timetable-quality.md)). [Step 9's local preview API and test page](schedule-preview-api.md) now use this feasibility solver. Administrator authentication, transactional booking/audit writes, stale-input revalidation, and lecturer rescheduling orchestration remain unimplemented. A valid draft is tied to captured input and does not reserve resources against concurrent changes.
