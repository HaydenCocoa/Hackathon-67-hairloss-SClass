"""Joint CP-SAT scheduling. Returns verified drafts, never booking writes.

Times are whole minutes from the horizon start (accepted 12 November 2026).
Compulsory rules are constraints, including the configured gap between two
classes sharing a room, lecturer or student. Step 8 preferences (student idle
time, lecturer idle time, room fit) only rank timetables that already satisfy
every compulsory rule.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from time import perf_counter
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from ortools.sat.python import cp_model
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from ..config import QualitySettings, SolverSettings
from .candidates import OccurrenceCandidates, WeeklyCandidates, generate_weekly_candidates
from .loader import ClassRequirement, SchedulingSnapshot
from .quality import QualityReport, measure_quality
from .requirements import ACTIVE_BOOKING_STATUSES
from .validator import BookingProposal, BookingValidator

MINUTE = timedelta(minutes=1)
# Below this much time left after the first complete answer, optimization is skipped.
MIN_OPTIMIZATION_SECONDS = 0.5
SolverOutcome = Literal["OPTIMAL", "FEASIBLE", "INFEASIBLE", "UNKNOWN", "MODEL_INVALID", "NO_PENDING_REQUIREMENTS"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ScheduleVerificationError(RuntimeError):
    """Internal solver/validator disagreement; never return unsafe assignments."""


class ClassPlacement(_Frozen):
    occurrence_id: UUID
    section_id: UUID
    lecturer_id: UUID
    room_id: UUID
    starts_at: datetime
    ends_at: datetime
    student_count: int = Field(gt=0)

    @field_validator("starts_at", "ends_at")
    @classmethod
    def aware_times(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("Placement timestamps must include timezone offsets")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def positive_interval(self) -> "ClassPlacement":
        if self.ends_at <= self.starts_at:
            raise ValueError("Placement must have positive duration")
        return self


class ScheduleDiagnostic(_Frozen):
    code: Literal["NO_PENDING_REQUIREMENTS", "NO_CANDIDATES", "JOINT_CONSTRAINTS_INFEASIBLE", "SEARCH_INCOMPLETE",
                  "MODEL_INVALID", "OPTIMIZATION_INCOMPLETE"]
    detail: str
    occurrence_id: UUID | None = None


class SolverStatistics(_Frozen):
    solver_ran: bool
    max_time_seconds: float
    num_search_workers: int
    random_seed: int
    elapsed_seconds: float = Field(ge=0)
    search_wall_time_seconds: float = Field(default=0, ge=0)
    branches: int = Field(default=0, ge=0)
    conflicts: int = Field(default=0, ge=0)
    optimization_ran: bool = False
    optimization_wall_time_seconds: float = Field(default=0, ge=0)
    objective_value: float | None = Field(default=None, description="Weighted preference score of the returned timetable (lower is better)")
    best_bound: float | None = Field(default=None, description="Lowest score the search could not rule out")


class ScheduleResult(_Frozen):
    status: SolverOutcome
    snapshot_revision: str
    week_start: date
    timezone: str
    required_count: int = Field(ge=0)
    placements: tuple[ClassPlacement, ...]
    candidate_failures: tuple[OccurrenceCandidates, ...]
    diagnostics: tuple[ScheduleDiagnostic, ...]
    statistics: SolverStatistics
    quality_optimized: bool = Field(default=False, description="True when the configured preferences ranked this timetable")
    quality: QualityReport | None = Field(default=None, description="Measurements of a complete timetable")

    @computed_field
    @property
    def has_solution(self) -> bool:
        return self.status in ("OPTIMAL", "FEASIBLE")

    @model_validator(mode="after")
    def complete_only(self) -> "ScheduleResult":
        if self.has_solution:
            if self.required_count == 0 or len(self.placements) != self.required_count:
                raise ValueError("A successful result must contain every pending lesson")
            if len({item.occurrence_id for item in self.placements}) != self.required_count:
                raise ValueError("A successful result must not duplicate lesson identities")
        elif self.placements:
            raise ValueError("An unsuccessful result cannot publish partial assignments")
        return self


@dataclass
class _Decision:
    requirement: ClassRequirement
    start: cp_model.IntVar
    duration: int  # minutes
    bounds: list[list[int]]  # allowed start ranges, minutes
    room_choices: dict[UUID, cp_model.IntVar]


def _minutes(value: datetime, origin: datetime) -> int:
    return (value - origin) // MINUTE


def _minutes_up(value: datetime, origin: datetime) -> int:
    return -((origin - value) // MINUTE)


def _build_model(snapshot: SchedulingSnapshot, candidates: WeeklyCandidates) -> tuple[cp_model.CpModel, list[_Decision]]:
    model = cp_model.CpModel()
    by_occurrence = {item.occurrence_id: item for item in candidates.occurrences}
    gap = snapshot.min_gap_minutes
    by_room = defaultdict(list)
    by_lecturer = defaultdict(list)
    by_student = defaultdict(list)
    intervals = []
    decisions = []

    for index, item in enumerate(sorted(snapshot.pending_requirements, key=lambda item: str(item.occurrence_id))):
        room_bounds = defaultdict(list)
        for candidate in by_occurrence[item.occurrence_id].ranges:
            # Candidate ranges are whole-minute starts, so these conversions are exact.
            room_bounds[candidate.room_id].append([
                _minutes(candidate.earliest_start, snapshot.horizon_starts_at),
                _minutes(candidate.latest_start, snapshot.horizon_starts_at),
            ])
        all_bounds = [bounds for room in room_bounds.values() for bounds in room]
        start = model.new_int_var_from_domain(cp_model.Domain.from_intervals(all_bounds), f"lesson_{index}_start")
        duration = item.duration_minutes
        # Each class occupies its resources for its duration PLUS the compulsory gap,
        # so two new classes sharing a room/lecturer/student are at least `gap` apart.
        interval = model.new_fixed_size_interval_var(start, duration + gap, f"lesson_{index}")
        intervals.append(interval)
        by_lecturer[item.lecturer_id].append(interval)
        for student_id in item.student_ids:
            by_student[student_id].append(index)

        choices = {}
        for room_index, (room_id, bounds) in enumerate(sorted(room_bounds.items(), key=lambda pair: str(pair[0]))):
            selected = model.new_bool_var(f"lesson_{index}_room_{room_index}")
            model.add_linear_expression_in_domain(start, cp_model.Domain.from_intervals(bounds)).only_enforce_if(selected)
            room_interval = model.new_optional_fixed_size_interval_var(start, duration + gap, selected, f"room_interval_{index}_{room_index}")
            by_room[room_id].append(room_interval)
            choices[room_id] = selected
        model.add_exactly_one(list(choices.values()))
        decisions.append(_Decision(item, start, duration, all_bounds, choices))

    for group in [*by_lecturer.values(), *by_room.values()]:
        if len(group) > 1:
            model.add_no_overlap(group)
    # Students attending exactly the same lessons need only one identical
    # no-overlap constraint; cross-intake memberships remain in the signatures.
    student_groups = {tuple(indices) for indices in by_student.values() if len(indices) > 1}
    for indices in sorted(student_groups):
        model.add_no_overlap([intervals[index] for index in indices])
    return model, decisions


def _add_objective(model: cp_model.CpModel, decisions: list[_Decision], snapshot: SchedulingSnapshot,
                   quality: QualitySettings) -> bool:
    """Add the weighted step 8 preferences. Returns False when there is nothing to optimize."""
    origin, zone = snapshot.horizon_starts_at, ZoneInfo(snapshot.timezone)
    windows = [(window.day, _minutes(window.starts_at, origin), _minutes_up(window.ends_at, origin))
               for window in sorted(snapshot.opening_windows, key=lambda item: item.starts_at)]
    day_index = {day: k for k, (day, _, _) in enumerate(windows)}

    # Which teaching day each new class lands on (its possible starts may span several days).
    on_day: list[dict[int, cp_model.IntVar]] = []
    for i, decision in enumerate(decisions):
        days = {}
        for k, (_, opens, closes) in enumerate(windows):
            low, high = opens, closes - decision.duration
            if any(b_low <= high and low <= b_high for b_low, b_high in decision.bounds):
                chosen = model.new_bool_var(f"lesson_{i}_day_{k}")
                model.add(decision.start >= low).only_enforce_if(chosen)
                model.add(decision.start <= high).only_enforce_if(chosen)
                days[k] = chosen
        if not days:
            return False  # cannot happen for candidates built from opening windows; never risk infeasibility
        model.add_exactly_one(list(days.values()))
        on_day.append(days)

    # Fixed bookings per person and teaching day (they cannot move but shape each day's span).
    def fixed_by_day(bookings) -> dict[int, list[tuple[int, int]]]:
        days: dict[int, list[tuple[int, int]]] = defaultdict(list)
        for booking in bookings:
            k = day_index.get(booking.starts_at.astimezone(zone).date())
            if k is not None:
                days[k].append((_minutes(booking.starts_at, origin), _minutes_up(booking.ends_at, origin)))
        return days

    fixed = [*(b for b in snapshot.class_bookings if b.status in ACTIVE_BOOKING_STATUSES),
             *(m for m in snapshot.meeting_bookings if m.status == "scheduled")]
    terms = []

    def add_person(lessons: tuple[int, ...], fixed_days: dict[int, list[tuple[int, int]]], weight: int, name: str) -> None:
        # Idle = (last end - first start) - minutes in new classes; fixed class minutes are a constant and omitted.
        for k in sorted({k for i in lessons for k in on_day[i]}):
            _, opens, closes = windows[k]
            day_fixed = fixed_days.get(k, [])
            low = min([opens, *(s for s, _ in day_fixed)])
            high = max([closes, *(e for _, e in day_fixed)])
            first = model.new_int_var(low, high, f"{name}_day_{k}_first")
            last = model.new_int_var(low, high, f"{name}_day_{k}_last")
            model.add(last >= first)
            busy = []
            for i in lessons:
                chosen = on_day[i].get(k)
                if chosen is not None:
                    model.add(first <= decisions[i].start).only_enforce_if(chosen)
                    model.add(last >= decisions[i].start + decisions[i].duration).only_enforce_if(chosen)
                    busy.append(decisions[i].duration * chosen)
            for s, e in day_fixed:
                model.add(first <= s)
                model.add(last >= e)
            # Always true (this person's new classes cannot overlap); it gives the search a useful lower bound.
            model.add(last - first >= sum(busy))
            terms.append(weight * (last - first - sum(busy)))

    student_weight = quality.weight("student_idle")
    if student_weight:
        lessons_of: dict[UUID, list[int]] = defaultdict(list)
        for i, decision in enumerate(decisions):
            for student_id in decision.requirement.student_ids:
                lessons_of[student_id].append(i)
        student_fixed: dict[UUID, list] = defaultdict(list)
        for booking in fixed:
            for student_id in booking.student_ids & lessons_of.keys():
                student_fixed[student_id].append(booking)
        # Students with the same new lessons and the same fixed day shapes share one set of variables.
        signatures = Counter()
        for student_id, lessons in lessons_of.items():
            days = fixed_by_day(student_fixed.get(student_id, ()))
            signatures[(tuple(lessons), tuple(sorted((k, tuple(sorted(v))) for k, v in days.items())))] += 1
        for n, ((lessons, days), count) in enumerate(sorted(signatures.items())):
            add_person(lessons, {k: list(v) for k, v in days}, student_weight * count, f"students_{n}")

    lecturer_weight = quality.weight("lecturer_idle")
    if lecturer_weight:
        lessons_by_lecturer: dict[UUID, list[int]] = defaultdict(list)
        for i, decision in enumerate(decisions):
            lessons_by_lecturer[decision.requirement.lecturer_id].append(i)
        for n, (lecturer_id, lessons) in enumerate(sorted(lessons_by_lecturer.items(), key=lambda pair: str(pair[0]))):
            days = fixed_by_day(b for b in fixed if b.lecturer_id == lecturer_id)
            add_person(tuple(lessons), days, lecturer_weight, f"lecturer_{n}")

    room_weight = quality.weight("room_fit")
    if room_weight:
        rooms = {room.id: room for room in snapshot.rooms}
        for decision in decisions:
            for room_id, selected in decision.room_choices.items():
                empty = rooms[room_id].capacity - decision.requirement.student_count
                if empty:
                    terms.append(room_weight * empty * selected)

    if not terms:
        return False
    model.minimize(sum(terms))
    return True


def verify_placements(snapshot: SchedulingSnapshot, placements: tuple[ClassPlacement, ...]) -> None:
    """Raise unless placements cover every pending lesson once, each passes
    booking validation, and no two of them share a room, lecturer or student
    within the compulsory gap."""
    pending = {item.occurrence_id: item for item in snapshot.pending_requirements}
    if len(placements) != len(pending) or {item.occurrence_id for item in placements} != set(pending):
        raise ScheduleVerificationError("Solver output does not cover every pending lesson exactly once")
    validator = BookingValidator(snapshot)
    for item in placements:
        source = pending[item.occurrence_id]
        checked = validator.validate(BookingProposal(occurrence_id=item.occurrence_id, room_id=item.room_id, starts_at=item.starts_at))
        if (not checked.valid or checked.ends_at != item.ends_at or item.section_id != source.section_id
                or item.lecturer_id != source.lecturer_id or item.student_count != source.student_count):
            raise ScheduleVerificationError("A generated assignment disagrees with booking validation")
    gap = timedelta(minutes=snapshot.min_gap_minutes)
    ordered = sorted(placements, key=lambda item: (item.starts_at, str(item.occurrence_id)))
    for index, left in enumerate(ordered):
        for right in ordered[index + 1:]:
            if right.starts_at >= left.ends_at + gap:
                break
            if (left.room_id == right.room_id or left.lecturer_id == right.lecturer_id
                    or pending[left.occurrence_id].student_ids & pending[right.occurrence_id].student_ids):
                raise ScheduleVerificationError("Generated lessons overlap or are closer than the required gap for shared resources")


# Original private name, kept for existing callers and tests.
_verify_placements = verify_placements


def _solver(options: SolverSettings, seconds: float) -> cp_model.CpSolver:
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = seconds
    solver.parameters.num_search_workers = options.num_search_workers
    solver.parameters.random_seed = options.random_seed
    solver.parameters.log_search_progress = False
    return solver


def _placements(solver: cp_model.CpSolver, decisions: list[_Decision], origin: datetime) -> tuple[ClassPlacement, ...]:
    placements = []
    for decision in decisions:
        rooms = [room_id for room_id, selected in decision.room_choices.items() if solver.value(selected)]
        if len(rooms) != 1:
            raise ScheduleVerificationError("The solver did not select exactly one room per lesson")
        starts_at = origin + timedelta(minutes=solver.value(decision.start))
        placements.append(ClassPlacement(
            occurrence_id=decision.requirement.occurrence_id, section_id=decision.requirement.section_id,
            lecturer_id=decision.requirement.lecturer_id, room_id=rooms[0], starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=decision.duration), student_count=decision.requirement.student_count,
        ))
    return tuple(placements)


def solve_weekly_schedule(snapshot: SchedulingSnapshot, options: SolverSettings | None = None,
                          quality: QualitySettings | None = None) -> ScheduleResult:
    """Find a complete draft for pending lessons; never writes to the database.

    Pass settings.scheduling.solver and settings.scheduling.quality to use the
    configured search options and preferences. The time limit covers both CP-SAT
    searches (first a complete valid timetable, then improving it with the
    remaining time), not loading, candidate construction or QA.
    """
    started = perf_counter()
    options = SolverSettings.model_validate(options.model_dump() if options is not None else {})
    quality = quality if quality is not None else QualitySettings()
    required_count = len(snapshot.pending_requirements)
    runs: list[cp_model.CpSolver] = []
    extra: dict = {}

    def result(status: SolverOutcome, *, placements=(), failures=(), diagnostics=(), optimized=False) -> ScheduleResult:
        statistics = SolverStatistics(
            solver_ran=bool(runs), max_time_seconds=options.max_time_seconds,
            num_search_workers=options.num_search_workers, random_seed=options.random_seed,
            elapsed_seconds=perf_counter() - started,
            search_wall_time_seconds=sum(run.wall_time for run in runs),
            branches=sum(run.num_branches for run in runs), conflicts=sum(run.num_conflicts for run in runs),
            **extra,
        )
        return ScheduleResult(status=status, snapshot_revision=snapshot.revision, week_start=snapshot.week_start,
                              timezone=snapshot.timezone, required_count=required_count, placements=placements,
                              candidate_failures=failures, diagnostics=diagnostics, statistics=statistics,
                              quality_optimized=optimized,
                              quality=measure_quality(snapshot, placements) if placements else None)

    if not required_count:
        return result("NO_PENDING_REQUIREMENTS", diagnostics=(ScheduleDiagnostic(
            code="NO_PENDING_REQUIREMENTS", detail="There are no pending teaching requirements in this snapshot."),))
    candidates = generate_weekly_candidates(snapshot)
    failures = tuple(item for item in candidates.occurrences if not item.has_candidates)
    if failures:
        return result("INFEASIBLE", failures=failures, diagnostics=tuple(ScheduleDiagnostic(
            code="NO_CANDIDATES", detail="This pending lesson has no valid room/start range in the captured week.",
            occurrence_id=item.occurrence_id) for item in failures))
    model, decisions = _build_model(snapshot, candidates)
    if model.validate():
        return result("MODEL_INVALID", diagnostics=(ScheduleDiagnostic(
            code="MODEL_INVALID", detail="The generated solver model is invalid; no timetable was returned."),))

    # Search 1: any complete timetable that satisfies every compulsory rule.
    first = _solver(options, options.max_time_seconds)
    runs.append(first)
    status = first.solve(model)
    names: dict[int, SolverOutcome] = {
        cp_model.OPTIMAL: "OPTIMAL", cp_model.FEASIBLE: "FEASIBLE", cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.MODEL_INVALID: "MODEL_INVALID", cp_model.UNKNOWN: "UNKNOWN",
    }
    if status not in names:
        raise ScheduleVerificationError("The solver returned an unsupported status")
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        complete = _placements(first, decisions, snapshot.horizon_starts_at)
        verify_placements(snapshot, complete)
        if not quality.active:
            return result(names[status], placements=complete)

        # Search 2: improve that timetable under the configured preferences, starting from it.
        remaining = options.max_time_seconds - first.wall_time
        if remaining < MIN_OPTIMIZATION_SECONDS or not _add_objective(model, decisions, snapshot, quality):
            return result("FEASIBLE", placements=complete, diagnostics=(ScheduleDiagnostic(
                code="OPTIMIZATION_INCOMPLETE", detail="A valid timetable was found but there was no time left to improve it."),))
        for decision in decisions:
            model.add_hint(decision.start, first.value(decision.start))
            for selected in decision.room_choices.values():
                model.add_hint(selected, first.value(selected))
        second = _solver(options, remaining)
        runs.append(second)
        improved = second.solve(model)
        extra.update(optimization_ran=True, optimization_wall_time_seconds=second.wall_time)
        if improved in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            better = _placements(second, decisions, snapshot.horizon_starts_at)
            verify_placements(snapshot, better)
            extra.update(objective_value=second.objective_value, best_bound=second.best_objective_bound)
            # OPTIMAL now means: best possible under the configured preferences.
            return result("OPTIMAL" if improved == cp_model.OPTIMAL else "FEASIBLE", placements=better, optimized=True)
        return result("FEASIBLE", placements=complete, diagnostics=(ScheduleDiagnostic(
            code="OPTIMIZATION_INCOMPLETE", detail="A valid timetable was found but the improvement search did not finish; the first valid timetable is returned."),))
    if status == cp_model.INFEASIBLE:
        diagnostic = ScheduleDiagnostic(code="JOINT_CONSTRAINTS_INFEASIBLE", detail="No joint assignment satisfies all fixed and new-class constraints in this captured week.")
    elif status == cp_model.MODEL_INVALID:
        diagnostic = ScheduleDiagnostic(code="MODEL_INVALID", detail="The solver rejected the model; this is not proof that the timetable is impossible.")
    else:
        diagnostic = ScheduleDiagnostic(code="SEARCH_INCOMPLETE", detail="Search ended without a complete solution or a proof of impossibility.")
    return result(names[status], diagnostics=(diagnostic,))
