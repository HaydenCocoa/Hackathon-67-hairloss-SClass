from datetime import timedelta

import pytest
from ortools.sat.python import cp_model
from pydantic import ValidationError

from backend.app.config import SolverSettings, load_settings
from backend.app.scheduling import solver as scheduler
from backend.app.scheduling.candidates import generate_weekly_candidates
from backend.app.scheduling.loader import LecturerInput
from backend.app.scheduling.solver import ClassPlacement, ScheduleVerificationError, solve_weekly_schedule
from backend.app.scheduling.validator import BookingIssue, BookingProposal, BookingValidator
from backend.tests.test_booking_validator import booking, instant, snapshot as sample_snapshot, uid, with_original


@pytest.fixture
def snapshot(sample_snapshot):
    return sample_snapshot.model_copy(update={"opening_windows": sample_snapshot.opening_windows[:1]})


def scenario(snapshot, specifications, *, window_minutes=90, room_ids=(1, 3)):
    source = snapshot.requirements[0]
    requirements = []
    for index, changes in enumerate(specifications):
        fields = dict(occurrence_id=uid(100 + index), section_id=uid(200 + index), plan_id=uid(300 + index),
                      intake_id=uid(400 + index), lecturer_id=uid(20 + index),
                      student_ids=frozenset([uid(5000 + index)]), duration_minutes=90,
                      booking_status=None, class_session_id=None, starts_at=None, room_id=None,
                      requirement_status="required", needs_scheduling=True)
        fields.update(changes)
        requirements.append(source.model_copy(update=fields))
    first = snapshot.opening_windows[0]
    window = first.model_copy(update={"ends_at": first.starts_at + timedelta(minutes=window_minutes)})
    return snapshot.model_copy(update={
        "requirements": tuple(requirements), "opening_windows": (window,),
        "rooms": tuple(item for item in snapshot.rooms if item.id in {uid(n) for n in room_ids}),
        "lecturers": tuple(LecturerInput(id=teacher) for teacher in sorted({r.lecturer_id for r in requirements}, key=str)),
    })


def test_generates_complete_verified_draft_without_mutating_snapshot(snapshot):
    before = snapshot.model_dump_json()
    result = solve_weekly_schedule(snapshot)
    assert result.has_solution and result.status in ("OPTIMAL", "FEASIBLE")
    assert result.required_count == len(result.placements) == 1
    assert result.snapshot_revision == snapshot.revision
    assert result.statistics.solver_ran
    assert result.statistics.max_time_seconds == 10
    assert result.statistics.num_search_workers == 1
    assert result.statistics.random_seed == 0
    assignment = result.placements[0]
    assert BookingValidator(snapshot).validate(BookingProposal(
        occurrence_id=assignment.occurrence_id, room_id=assignment.room_id, starts_at=assignment.starts_at,
    )).valid
    assert snapshot.model_dump_json() == before
    assert '"student_ids"' not in result.model_dump_json()
    with pytest.raises(ValidationError):
        assignment.room_id = uid(999)


def test_exact_fit_uses_whole_minute_starts(snapshot):
    first = snapshot.opening_windows[0]
    window = first.model_copy(update={"ends_at": first.starts_at + timedelta(minutes=90)})
    result = solve_weekly_schedule(snapshot.model_copy(update={"opening_windows": (window,)}))
    assert result.has_solution
    assert (result.placements[0].starts_at, result.placements[0].ends_at) == (window.starts_at, window.ends_at)
    # A window opening part-way through a minute leaves no whole-minute start for an exact fit.
    start = first.starts_at + timedelta(microseconds=123456)
    shifted = first.model_copy(update={"starts_at": start, "ends_at": start + timedelta(minutes=90)})
    result = solve_weekly_schedule(snapshot.model_copy(update={"opening_windows": (shifted,)}))
    assert result.status == "INFEASIBLE" and result.diagnostics[0].code == "NO_CANDIDATES"


@pytest.mark.parametrize("shared", ["lecturer", "student", "room"])
def test_joint_conflicts_can_be_infeasible_even_when_every_lesson_has_candidates(snapshot, shared):
    specifications = [{}, {}]
    rooms = (1, 3)
    if shared == "lecturer":
        specifications = [{"lecturer_id": uid(20)}, {"lecturer_id": uid(20)}]
    elif shared == "student":
        specifications = [{"student_ids": frozenset([uid(10)])}, {"student_ids": frozenset([uid(10)])}]
    else:
        rooms = (1,)
    snapshot = scenario(snapshot, specifications, room_ids=rooms)
    assert not generate_weekly_candidates(snapshot).blocked_occurrence_ids
    result = solve_weekly_schedule(snapshot)
    assert result.status == "INFEASIBLE"
    assert not result.has_solution and result.placements == ()
    assert result.candidate_failures == ()
    assert result.diagnostics[0].code == "JOINT_CONSTRAINTS_INFEASIBLE"
    assert result.statistics.solver_ran
    if shared == "student":
        assert snapshot.requirements[0].intake_id != snapshot.requirements[1].intake_id
        assert snapshot.requirements[0].lecturer_id != snapshot.requirements[1].lecturer_id


def test_shared_lecturer_and_student_can_have_adjacent_classes_without_a_break(snapshot):
    snapshot = scenario(snapshot, [
        {"lecturer_id": uid(20), "student_ids": frozenset([uid(10)])},
        {"lecturer_id": uid(20), "student_ids": frozenset([uid(10)])},
    ], window_minutes=180, room_ids=(1,))
    result = solve_weekly_schedule(snapshot)
    assert result.has_solution
    ordered = sorted(result.placements, key=lambda item: item.starts_at)
    assert ordered[0].starts_at == snapshot.opening_windows[0].starts_at
    assert ordered[0].ends_at == ordered[1].starts_at
    assert ordered[1].ends_at == snapshot.opening_windows[0].ends_at


def test_independent_classes_can_run_in_parallel_in_different_rooms(snapshot):
    snapshot = scenario(snapshot, [{}, {}])
    result = solve_weekly_schedule(snapshot)
    assert result.has_solution and len(result.placements) == 2
    assert result.placements[0].starts_at == result.placements[1].starts_at
    assert result.placements[0].room_id != result.placements[1].room_id


def test_joint_room_choice_preserves_the_only_room_available_to_another_lesson(snapshot):
    # A lab can use either room, but the lecture can only use the classroom.
    # Scheduling the lab first into the classroom would fail unnecessarily.
    snapshot = scenario(snapshot, [{"course_type": "lab"}, {"course_type": "lecture"}], room_ids=(1, 2))
    result = solve_weekly_schedule(snapshot)
    assert result.has_solution
    rooms = {item.occurrence_id: item.room_id for item in result.placements}
    assert rooms == {uid(100): uid(2), uid(101): uid(1)}


def test_room_presence_and_room_specific_start_domain_stay_linked(snapshot):
    snapshot = scenario(snapshot, [{}, {}], window_minutes=180)
    first = snapshot.opening_windows[0].starts_at
    early = booking(id=uid(80), room_id=uid(1), lecturer_id=uid(90), student_ids={uid(91)},
                    start=first.isoformat())
    late = booking(id=uid(81), room_id=uid(3), lecturer_id=uid(90), student_ids={uid(91)},
                   start=(first + timedelta(minutes=90)).isoformat())
    snapshot = snapshot.model_copy(update={"class_bookings": (early, late)})
    result = solve_weekly_schedule(snapshot)
    assert result.has_solution
    assert {(item.room_id, item.starts_at) for item in result.placements} == {
        (uid(3), first), (uid(1), first + timedelta(minutes=90)),
    }


def test_disjoint_opening_domains_never_allow_starting_in_a_closed_gap(snapshot):
    first = snapshot.opening_windows[0].model_copy(update={"ends_at": instant("2026-11-09T10:00:00+08:00")})
    second = first.model_copy(update={"starts_at": instant("2026-11-09T14:00:00+08:00"),
                                      "ends_at": instant("2026-11-09T15:30:00+08:00")})
    snapshot = snapshot.model_copy(update={"opening_windows": (first, second)})
    result = solve_weekly_schedule(snapshot)
    assert result.has_solution
    assert result.placements[0].starts_at in {first.starts_at, second.starts_at}


def test_fixed_bookings_are_preserved_without_requiring_legacy_conflicts_to_be_repaired(snapshot):
    snapshot = scenario(snapshot, [{}], window_minutes=330, room_ids=(1,))
    fixed = (booking(id=uid(80), room_id=uid(1), start="2026-11-09T09:00:00+08:00"),
             booking(id=uid(81), room_id=uid(1), start="2026-11-09T10:00:00+08:00"))
    snapshot = snapshot.model_copy(update={"class_bookings": fixed})
    before = snapshot.model_dump_json()
    result = solve_weekly_schedule(snapshot)
    assert result.has_solution
    assert result.placements[0].starts_at >= instant("2026-11-09T11:30:00+08:00")
    assert snapshot.model_dump_json() == before


def test_one_missing_candidate_blocks_the_whole_draft_instead_of_dropping_a_lesson(snapshot):
    snapshot = scenario(snapshot, [{}, {"course_type": "others"}])
    result = solve_weekly_schedule(snapshot)
    assert result.status == "INFEASIBLE" and result.placements == ()
    assert result.required_count == 2
    assert not result.statistics.solver_ran
    assert [item.occurrence_id for item in result.candidate_failures] == [uid(101)]
    assert result.diagnostics[0].code == "NO_CANDIDATES"


def test_no_pending_requirements_is_explicit_without_running_solver(snapshot, monkeypatch):
    snapshot = snapshot.model_copy(update={"requirements": ()})
    monkeypatch.setattr(cp_model, "CpSolver", lambda: pytest.fail("empty input must not run solver"))
    result = solve_weekly_schedule(snapshot)
    assert result.status == "NO_PENDING_REQUIREMENTS"
    assert not result.has_solution and result.required_count == 0 and not result.statistics.solver_ran
    assert result.placements == ()


def test_already_scheduled_and_cancelled_lessons_are_not_regenerated(snapshot):
    snapshot = with_original(snapshot)
    original = snapshot.requirements[0]
    new = original.model_copy(update={"occurrence_id": uid(200), "class_session_id": None, "booking_status": None,
                                      "starts_at": None, "room_id": None, "needs_scheduling": True})
    cancelled = new.model_copy(update={"occurrence_id": uid(201), "requirement_status": "cancelled", "needs_scheduling": False})
    snapshot = snapshot.model_copy(update={"requirements": (original, new, cancelled)})
    result = solve_weekly_schedule(snapshot)
    assert result.has_solution and result.required_count == 1
    assert [item.occurrence_id for item in result.placements] == [uid(200)]
    assert snapshot.class_bookings[0].id == original.class_session_id


def test_real_search_time_limit_is_unknown_not_infeasible(snapshot):
    snapshot = scenario(snapshot, [{}, {}, {}], window_minutes=540)
    result = solve_weekly_schedule(snapshot, SolverSettings(max_time_seconds=1e-9))
    assert result.status == "UNKNOWN"
    assert result.statistics.solver_ran and not result.has_solution
    assert result.placements == () and result.candidate_failures == ()
    assert result.diagnostics[0].code == "SEARCH_INCOMPLETE"


def test_feasible_status_retains_a_complete_real_solution(snapshot, monkeypatch):
    real_solve = cp_model.CpSolver.solve

    def report_feasible(self, model):
        actual = real_solve(self, model)
        assert actual in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        return cp_model.FEASIBLE

    monkeypatch.setattr(cp_model.CpSolver, "solve", report_feasible)
    result = solve_weekly_schedule(snapshot)
    assert result.status == "FEASIBLE" and result.has_solution
    assert len(result.placements) == result.required_count


def test_invalid_model_is_not_reported_as_impossible_or_solved(snapshot, monkeypatch):
    # Inject a failed model-health check, not a fabricated feasible assignment.
    monkeypatch.setattr(cp_model.CpModel, "validate", lambda self: "injected validation error")
    result = solve_weekly_schedule(snapshot)
    assert result.status == "MODEL_INVALID"
    assert not result.has_solution and not result.statistics.solver_ran
    assert result.placements == () and result.diagnostics[0].code == "MODEL_INVALID"


def test_postsolve_validator_disagreement_cannot_publish_assignments(snapshot, monkeypatch):
    real_validate = BookingValidator.validate

    def disagree(self, proposal):
        result = real_validate(self, proposal)
        return result.model_copy(update={"issues": (BookingIssue(code="ROOM_INACTIVE", detail="Injected validator disagreement"),)})

    monkeypatch.setattr(BookingValidator, "validate", disagree)
    with pytest.raises(ScheduleVerificationError, match="disagrees"):
        solve_weekly_schedule(snapshot)


def test_independent_postsolve_check_detects_new_class_student_clashes(snapshot):
    snapshot = scenario(snapshot, [{"student_ids": frozenset([uid(10)])}, {"student_ids": frozenset([uid(10)])}])
    starts_at = snapshot.opening_windows[0].starts_at
    placements = tuple(ClassPlacement(
        occurrence_id=item.occurrence_id, section_id=item.section_id, lecturer_id=item.lecturer_id,
        room_id=uid(room), starts_at=starts_at, ends_at=starts_at + timedelta(minutes=90), student_count=item.student_count,
    ) for item, room in zip(snapshot.requirements, [1, 3]))
    with pytest.raises(ScheduleVerificationError, match="overlap"):
        scheduler._verify_placements(snapshot, placements)


@pytest.mark.parametrize("changes", [
    {"max_time_seconds": 0}, {"max_time_seconds": float("inf")}, {"max_time_seconds": float("nan")},
    {"num_search_workers": 0}, {"num_search_workers": True}, {"num_search_workers": 33},
    {"random_seed": -1}, {"random_seed": 2147483648},
])
def test_invalid_search_settings_fail_validation(changes):
    with pytest.raises(ValidationError):
        SolverSettings.model_validate(changes)


def test_search_options_are_configurable_and_recorded(snapshot):
    # 10 s, then 120 s (12 November 2026), then 280 s (13 November 2026): the whole request must end
    # within Vercel's 300 s function limit (Hobby maximum), leaving about 20 s for loading and checking.
    configured = load_settings().scheduling.solver.max_time_seconds
    assert configured == 280 and configured <= 300 - 20
    options = SolverSettings(max_time_seconds=2, num_search_workers=1, random_seed=7)
    result = solve_weekly_schedule(snapshot, options)
    assert result.has_solution
    assert result.statistics.max_time_seconds == 2 and result.statistics.random_seed == 7


def test_mvp_sized_week_schedules_six_components_for_forty_shared_students(sample_snapshot):
    source = sample_snapshot.requirements[0]
    students = frozenset(uid(n) for n in range(5000, 5040))
    requirements = tuple(source.model_copy(update={
        "occurrence_id": uid(100 + index), "section_id": uid(200 + index),
        "course_type": kind, "duration_minutes": 120, "student_ids": students,
        "lecturer_id": uid(20 + index // 2),
    }) for index, kind in enumerate(["lecture", "lab", "lecture", "lab", "lecture", "tutorial"]))
    snapshot = sample_snapshot.model_copy(update={
        "requirements": requirements,
        "lecturers": tuple(LecturerInput(id=uid(n)) for n in [20, 21, 22]),
    })
    result = solve_weekly_schedule(snapshot, SolverSettings(max_time_seconds=2))
    assert result.has_solution and result.required_count == len(result.placements) == 6
    assert all(item.student_count == 40 for item in result.placements)
    ordered = sorted(result.placements, key=lambda item: item.starts_at)
    assert all(left.ends_at <= right.starts_at for left, right in zip(ordered, ordered[1:]))
    assert len({item.starts_at.date() for item in result.placements}) >= 2
