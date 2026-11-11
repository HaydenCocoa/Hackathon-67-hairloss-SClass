"""Joint feasibility scheduling. Returns verified drafts, never booking writes."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from time import perf_counter
from typing import Literal
from uuid import UUID

from ortools.sat.python import cp_model
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from ..config import SolverSettings
from .candidates import OccurrenceCandidates, WeeklyCandidates, generate_weekly_candidates
from .loader import ClassRequirement, SchedulingSnapshot
from .validator import BookingProposal, BookingValidator

MICROSECOND = timedelta(microseconds=1)
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
    code: Literal["NO_PENDING_REQUIREMENTS", "NO_CANDIDATES", "JOINT_CONSTRAINTS_INFEASIBLE", "SEARCH_INCOMPLETE", "MODEL_INVALID"]
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
    end: cp_model.IntVar
    room_choices: dict[UUID, cp_model.IntVar]


def _ticks(value: datetime, origin: datetime) -> int:
    # Integer timedelta division avoids floating-point timestamp rounding.
    return (value - origin) // MICROSECOND


def _build_model(snapshot: SchedulingSnapshot, candidates: WeeklyCandidates) -> tuple[cp_model.CpModel, list[_Decision]]:
    model = cp_model.CpModel()
    by_occurrence = {item.occurrence_id: item for item in candidates.occurrences}
    by_room = defaultdict(list)
    by_lecturer = defaultdict(list)
    by_student = defaultdict(list)
    intervals = []
    decisions = []

    for index, item in enumerate(sorted(snapshot.pending_requirements, key=lambda item: str(item.occurrence_id))):
        room_bounds = defaultdict(list)
        for candidate in by_occurrence[item.occurrence_id].ranges:
            room_bounds[candidate.room_id].append([
                _ticks(candidate.earliest_start, snapshot.horizon_starts_at),
                _ticks(candidate.latest_start, snapshot.horizon_starts_at),
            ])
        all_bounds = [bounds for room in room_bounds.values() for bounds in room]
        start = model.new_int_var_from_domain(cp_model.Domain.from_intervals(all_bounds), f"lesson_{index}_start")
        duration = item.duration_minutes * 60 * 1000000
        end = model.new_int_var(min(low for low, _ in all_bounds) + duration,
                                max(high for _, high in all_bounds) + duration, f"lesson_{index}_end")
        interval = model.new_interval_var(start, duration, end, f"lesson_{index}")
        intervals.append(interval)
        by_lecturer[item.lecturer_id].append(interval)
        for student_id in item.student_ids:
            by_student[student_id].append(index)

        choices = {}
        for room_index, (room_id, bounds) in enumerate(sorted(room_bounds.items(), key=lambda pair: str(pair[0]))):
            selected = model.new_bool_var(f"lesson_{index}_room_{room_index}")
            model.add_linear_expression_in_domain(start, cp_model.Domain.from_intervals(bounds)).only_enforce_if(selected)
            room_interval = model.new_optional_interval_var(start, duration, end, selected, f"room_interval_{index}_{room_index}")
            by_room[room_id].append(room_interval)
            choices[room_id] = selected
        model.add_exactly_one(list(choices.values()))
        decisions.append(_Decision(item, start, end, choices))

    for group in [*by_lecturer.values(), *by_room.values()]:
        if len(group) > 1:
            model.add_no_overlap(group)
    # Students attending exactly the same lessons need only one identical
    # no-overlap constraint; cross-intake memberships remain in the signatures.
    student_groups = {tuple(indices) for indices in by_student.values() if len(indices) > 1}
    for indices in sorted(student_groups):
        model.add_no_overlap([intervals[index] for index in indices])
    return model, decisions


def verify_placements(snapshot: SchedulingSnapshot, placements: tuple[ClassPlacement, ...]) -> None:
    """Raise unless placements cover every pending lesson once, each passes
    booking validation, and no two of them share a room, lecturer or student."""
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
    ordered = sorted(placements, key=lambda item: (item.starts_at, str(item.occurrence_id)))
    for index, left in enumerate(ordered):
        for right in ordered[index + 1:]:
            if right.starts_at >= left.ends_at:
                break
            if (left.room_id == right.room_id or left.lecturer_id == right.lecturer_id
                    or pending[left.occurrence_id].student_ids & pending[right.occurrence_id].student_ids):
                raise ScheduleVerificationError("Generated lessons overlap for shared resources")


# Original private name, kept for existing callers and tests.
_verify_placements = verify_placements


def solve_weekly_schedule(snapshot: SchedulingSnapshot, options: SolverSettings | None = None) -> ScheduleResult:
    """Find a complete draft for pending lessons; no objective or database write.

    Pass settings.scheduling.solver to use configured search options. The time
    limit applies to CP-SAT search, not loading, candidate construction, or QA.
    """
    started = perf_counter()
    options = SolverSettings.model_validate(options.model_dump() if options is not None else {})
    required_count = len(snapshot.pending_requirements)
    solver: cp_model.CpSolver | None = None

    def result(status: SolverOutcome, *, placements=(), failures=(), diagnostics=()) -> ScheduleResult:
        statistics = SolverStatistics(
            solver_ran=solver is not None, max_time_seconds=options.max_time_seconds,
            num_search_workers=options.num_search_workers, random_seed=options.random_seed,
            elapsed_seconds=perf_counter() - started,
            search_wall_time_seconds=solver.wall_time if solver is not None else 0,
            branches=solver.num_branches if solver is not None else 0,
            conflicts=solver.num_conflicts if solver is not None else 0,
        )
        return ScheduleResult(status=status, snapshot_revision=snapshot.revision, week_start=snapshot.week_start,
                              timezone=snapshot.timezone, required_count=required_count, placements=placements,
                              candidate_failures=failures, diagnostics=diagnostics, statistics=statistics)

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
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = options.max_time_seconds
    solver.parameters.num_search_workers = options.num_search_workers
    solver.parameters.random_seed = options.random_seed
    solver.parameters.log_search_progress = False
    status = solver.solve(model)
    names: dict[int, SolverOutcome] = {
        cp_model.OPTIMAL: "OPTIMAL", cp_model.FEASIBLE: "FEASIBLE", cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.MODEL_INVALID: "MODEL_INVALID", cp_model.UNKNOWN: "UNKNOWN",
    }
    if status not in names:
        raise ScheduleVerificationError("The solver returned an unsupported status")
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        placements = []
        for decision in decisions:
            rooms = [room_id for room_id, selected in decision.room_choices.items() if solver.value(selected)]
            if len(rooms) != 1:
                raise ScheduleVerificationError("The solver did not select exactly one room per lesson")
            placements.append(ClassPlacement(
                occurrence_id=decision.requirement.occurrence_id, section_id=decision.requirement.section_id,
                lecturer_id=decision.requirement.lecturer_id, room_id=rooms[0],
                starts_at=snapshot.horizon_starts_at + timedelta(microseconds=solver.value(decision.start)),
                ends_at=snapshot.horizon_starts_at + timedelta(microseconds=solver.value(decision.end)),
                student_count=decision.requirement.student_count,
            ))
        complete = tuple(placements)
        _verify_placements(snapshot, complete)
        return result(names[status], placements=complete)
    if status == cp_model.INFEASIBLE:
        diagnostic = ScheduleDiagnostic(code="JOINT_CONSTRAINTS_INFEASIBLE", detail="No joint assignment satisfies all fixed and new-class constraints in this captured week.")
    elif status == cp_model.MODEL_INVALID:
        diagnostic = ScheduleDiagnostic(code="MODEL_INVALID", detail="The solver rejected the model; this is not proof that the timetable is impossible.")
    else:
        diagnostic = ScheduleDiagnostic(code="SEARCH_INCOMPLETE", detail="Search ended without a complete solution or a proof of impossibility.")
    return result(names[status], diagnostics=(diagnostic,))
