"""Step 8 (12 November 2026): compulsory 15-minute gap, auditorium-only-when-needed,
whole-minute starts, quality measurements and the weighted preferences."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from backend.app.config import QualitySettings, SolverSettings, load_settings
from backend.app.scheduling import solver as scheduler
from backend.app.scheduling.candidates import generate_candidates
from backend.app.scheduling.loader import MeetingBooking, RoomInput
from backend.app.scheduling.quality import measure_quality
from backend.app.scheduling.solver import ClassPlacement, ScheduleVerificationError, solve_weekly_schedule
from backend.app.scheduling.validator import validate_booking
from backend.tests.test_booking_validator import booking, change_requirement, instant, proposed, uid
from backend.tests.test_booking_validator import snapshot as sample_snapshot  # noqa: F401 (fixture)
from backend.tests.test_solver import scenario

PREFERENCES = load_settings().scheduling.quality


@pytest.fixture
def snapshot(sample_snapshot):  # noqa: F811
    return sample_snapshot.model_copy(update={"min_gap_minutes": 15, "reserved_room_types": frozenset({"auditorium"})})


def at(clock, day=9):
    return f"2026-11-{day:02d}T{clock}:00+08:00"


# ---------- Configuration ----------

def test_config_records_the_accepted_rules_and_preferences():
    scheduling = load_settings().scheduling
    assert scheduling.min_gap_minutes == 15
    assert scheduling.reserved_room_types == ("auditorium",)
    assert scheduling.quality.enabled and scheduling.quality.active
    assert [(item.name, item.weight) for item in scheduling.quality.objectives] == [
        ("student_idle", 100), ("lecturer_idle", 10), ("room_fit", 1)]


@pytest.mark.parametrize("data", [
    {"objectives": [{"name": "student_idle", "weight": 1}, {"name": "student_idle", "weight": 2}]},
    {"objectives": [{"name": "travel", "weight": 1}]},
    {"objectives": [{"name": "room_fit", "weight": -1}]},
    {"enabled": "yes"},
])
def test_invalid_quality_settings_fail_validation(data):
    with pytest.raises(ValidationError):
        QualitySettings.model_validate(data)


def test_quality_is_inactive_when_disabled_or_all_weights_are_zero():
    assert not QualitySettings().active
    assert not QualitySettings(enabled=True, objectives=[{"name": "room_fit", "weight": 0}]).active
    assert not QualitySettings(enabled=False, objectives=[{"name": "room_fit", "weight": 5}]).active


# ---------- Compulsory 15-minute gap ----------

@pytest.mark.parametrize("shared,code", [
    ({"lecturer_id": uid(20)}, "LECTURER_CONFLICT"),
    ({"student_ids": frozenset([uid(10)])}, "STUDENT_CONFLICT"),
    ({"room_id": uid(1)}, "ROOM_CONFLICT"),
])
@pytest.mark.parametrize("start,ok", [
    ("11:44", False), ("11:45", True),  # fixed class 10:00-11:30: next start needs 11:45
    ("08:16", False), ("08:15", True),  # a 90-minute class must end by 09:45 before it
])
def test_gap_applies_to_every_shared_resource_on_both_sides(snapshot, shared, code, start, ok):
    fixed = booking(start=at("10:00"), **{"room_id": uid(2), "lecturer_id": uid(21), "student_ids": frozenset([uid(12)]), **shared})
    snapshot = snapshot.model_copy(update={"class_bookings": (fixed,)})
    # 08:15 is before opening; use a wider window so only the gap decides.
    window = snapshot.opening_windows[0].model_copy(update={"starts_at": instant(at("07:00"))})
    snapshot = snapshot.model_copy(update={"opening_windows": (window,)})
    result = validate_booking(snapshot, proposed(snapshot, at(start)))
    assert result.valid is ok, result.reason_codes
    if not ok:
        assert result.reason_codes == (code,)
        assert "15 minutes" in result.issues[0].detail


def test_gap_also_applies_to_meetings(snapshot):
    meeting = MeetingBooking(id=uid(70), lecturer_id=uid(20), room_id=None, status="scheduled",
                             starts_at=instant(at("10:00")), ends_at=instant(at("11:00")), student_ids=frozenset())
    snapshot = snapshot.model_copy(update={"meeting_bookings": (meeting,)})
    assert validate_booking(snapshot, proposed(snapshot, at("11:10"))).reason_codes == ("LECTURER_CONFLICT",)
    assert validate_booking(snapshot, proposed(snapshot, at("11:15"))).valid


def test_without_a_configured_gap_back_to_back_is_allowed(snapshot):
    fixed = booking(start=at("10:00"), lecturer_id=uid(20))
    snapshot = snapshot.model_copy(update={"class_bookings": (fixed,), "min_gap_minutes": 0})
    assert validate_booking(snapshot, proposed(snapshot, at("11:30"))).valid


def test_candidate_ranges_keep_the_gap_around_fixed_bookings(snapshot):
    fixed = booking(start=at("10:00"), room_id=uid(1))  # 10:00-11:30 in the requested room
    snapshot = snapshot.model_copy(update={"class_bookings": (fixed,), "opening_windows": snapshot.opening_windows[:1]})
    ranges = [(item.earliest_start, item.latest_start) for item in generate_candidates(
        snapshot, snapshot.requirements[0].occurrence_id).ranges if item.room_id == uid(1)]
    # Before: 08:30 + 90 + 15 = 10:15 > 10:00, so nothing fits; after: from 11:45 until 16:30.
    assert ranges == [(instant(at("11:45")), instant(at("16:30")))]


@pytest.mark.parametrize("window,feasible", [(195, True), (194, False)])
def test_new_classes_sharing_a_lecturer_keep_the_gap(snapshot, window, feasible):
    snapshot = scenario(snapshot, [{"lecturer_id": uid(20)}, {"lecturer_id": uid(20)}], window_minutes=window)
    result = solve_weekly_schedule(snapshot)
    assert result.has_solution is feasible
    if feasible:
        first, second = sorted(result.placements, key=lambda item: item.starts_at)
        assert second.starts_at - first.ends_at == timedelta(minutes=15)
    else:
        assert result.diagnostics[0].code == "JOINT_CONSTRAINTS_INFEASIBLE"


def test_independent_check_rejects_new_classes_closer_than_the_gap(snapshot):
    snapshot = scenario(snapshot, [{"lecturer_id": uid(20)}, {"lecturer_id": uid(20)}], window_minutes=300)
    start = snapshot.opening_windows[0].starts_at
    placements = tuple(ClassPlacement(
        occurrence_id=item.occurrence_id, section_id=item.section_id, lecturer_id=item.lecturer_id,
        room_id=uid(room), starts_at=start + offset, ends_at=start + offset + timedelta(minutes=90),
        student_count=item.student_count,
    ) for item, room, offset in zip(snapshot.requirements, [1, 1], [timedelta(0), timedelta(minutes=100)]))
    with pytest.raises(ScheduleVerificationError, match="gap"):
        scheduler.verify_placements(snapshot, placements)


# ---------- Auditorium only when no other permitted room is large enough ----------

def test_auditorium_is_refused_when_a_classroom_can_seat_the_class(snapshot):
    # The fixture's classroom seats 2, exactly the roster.
    assert validate_booking(snapshot, proposed(snapshot, room=3)).reason_codes == ("ROOM_RESERVED_FOR_LARGE_CLASSES",)
    assert validate_booking(snapshot, proposed(snapshot, room=1)).valid


def test_auditorium_is_allowed_when_no_classroom_is_large_enough(snapshot):
    snapshot = change_requirement(snapshot, student_ids=frozenset([uid(10), uid(11), uid(12)]))
    assert validate_booking(snapshot, proposed(snapshot, room=3)).valid


def test_a_busy_classroom_does_not_unlock_the_auditorium(snapshot):
    busy = booking(start=at("09:00"), room_id=uid(1), duration=240)
    snapshot = snapshot.model_copy(update={"class_bookings": (busy,)})
    result = validate_booking(snapshot, proposed(snapshot, at("10:00"), room=3))
    assert result.reason_codes == ("ROOM_RESERVED_FOR_LARGE_CLASSES",)


def test_inactive_or_wrong_type_rooms_do_not_count_as_alternatives(snapshot):
    rooms = tuple(room.model_copy(update={"is_active": False}) if room.id == uid(1) else room for room in snapshot.rooms)
    snapshot = snapshot.model_copy(update={"rooms": rooms})
    # Only the (lecture-incompatible) lab and the 1-seat rooms remain: the auditorium is needed.
    assert validate_booking(snapshot, proposed(snapshot, room=3)).valid


def test_without_reserved_types_the_auditorium_is_an_ordinary_room(snapshot):
    snapshot = snapshot.model_copy(update={"reserved_room_types": frozenset()})
    assert validate_booking(snapshot, proposed(snapshot, room=3)).valid


def test_whole_minute_starts_are_required(snapshot):
    result = validate_booking(snapshot, proposed(snapshot, "2026-11-09T10:00:30+08:00"))
    assert result.reason_codes == ("START_NOT_WHOLE_MINUTE",)


# ---------- Measurements ----------

def test_measurements_are_hand_computable(snapshot):
    lesson = snapshot.requirements[0]  # students 10 and 11, lecturer 20
    fixed = (
        booking(id=uid(60), start=at("08:30"), duration=90, student_ids=frozenset([uid(10)]), lecturer_id=uid(21)),
        booking(id=uid(61), start=at("08:30"), duration=60, student_ids=frozenset(), lecturer_id=uid(20)),
        booking(id=uid(62), start=at("08:30", day=10), duration=90, student_ids=frozenset([uid(11)])),  # other day: ignored
    )
    snapshot = snapshot.model_copy(update={"class_bookings": fixed})
    start = instant(at("13:00"))
    placement = ClassPlacement(occurrence_id=lesson.occurrence_id, section_id=lesson.section_id, lecturer_id=lesson.lecturer_id,
                               room_id=uid(1), starts_at=start, ends_at=start + timedelta(minutes=90), student_count=2)
    report = measure_quality(snapshot, (placement,))
    # Student 10: 08:30-10:00 then 13:00-14:30 -> 180 idle, 360 span. Student 11: only the new class -> 0.
    assert (report.student_days, report.student_idle_minutes_total, report.student_idle_minutes_max) == (2, 180, 180)
    assert report.student_idle_minutes_average == 90.0 and report.longest_student_day_minutes == 360
    # Lecturer 20: 08:30-09:30 then 13:00-14:30 -> 210 idle.
    assert (report.lecturer_days, report.lecturer_idle_minutes_total) == (1, 210)
    # Classroom seats 2, roster 2.
    assert (report.empty_seats_total, report.seat_use_percent, report.reserved_room_classes) == (0, 100.0, 0)
    assert "uid" not in report.model_dump_json()


# ---------- Preferences ----------

def two_lessons_for_the_same_students(snapshot, window_minutes=570):
    students = frozenset([uid(10)])
    return scenario(snapshot, [{"student_ids": students}, {"student_ids": students}], window_minutes=window_minutes)


def test_preferences_close_student_gaps_down_to_the_compulsory_gap(snapshot):
    result = solve_weekly_schedule(two_lessons_for_the_same_students(snapshot), SolverSettings(max_time_seconds=5), PREFERENCES)
    assert result.has_solution and result.quality_optimized and result.statistics.optimization_ran
    assert result.quality.student_idle_minutes_total == 15
    assert result.statistics.objective_value is not None
    scheduler.verify_placements(two_lessons_for_the_same_students(snapshot), result.placements)


def test_room_fit_prefers_the_smallest_room_that_seats_the_class(snapshot):
    rooms = (RoomInput(id=uid(1), name="Big", building="B", capacity=50, room_type="classroom", is_active=True),
             RoomInput(id=uid(6), name="Snug", building="B", capacity=3, room_type="classroom", is_active=True))
    snapshot = snapshot.model_copy(update={"rooms": rooms})
    room_only = QualitySettings(enabled=True, objectives=[{"name": "room_fit", "weight": 1}])
    result = solve_weekly_schedule(snapshot, SolverSettings(max_time_seconds=5), room_only)
    assert result.status == "OPTIMAL" and result.placements[0].room_id == uid(6)
    assert result.quality.empty_seats_total == 1


def test_without_preferences_nothing_is_optimized_but_quality_is_measured(snapshot):
    result = solve_weekly_schedule(snapshot)
    assert result.has_solution and not result.quality_optimized and not result.statistics.optimization_ran
    assert result.quality is not None and result.quality.student_days == 2


def test_no_time_left_returns_the_first_valid_timetable(snapshot, monkeypatch):
    monkeypatch.setattr(scheduler, "MIN_OPTIMIZATION_SECONDS", 1e9)
    result = solve_weekly_schedule(snapshot, None, PREFERENCES)
    assert result.status == "FEASIBLE" and result.has_solution and not result.quality_optimized
    assert result.diagnostics[0].code == "OPTIMIZATION_INCOMPLETE" and result.quality is not None


def test_failed_improvement_search_falls_back_to_the_valid_timetable(snapshot, monkeypatch):
    from ortools.sat.python import cp_model
    real_solve = cp_model.CpSolver.solve
    calls = []

    def second_search_finds_nothing(self, model):
        calls.append(1)
        status = real_solve(self, model)
        return status if len(calls) == 1 else cp_model.UNKNOWN

    monkeypatch.setattr(cp_model.CpSolver, "solve", second_search_finds_nothing)
    result = solve_weekly_schedule(snapshot, None, PREFERENCES)
    assert len(calls) == 2 and result.status == "FEASIBLE" and not result.quality_optimized
    assert result.diagnostics[0].code == "OPTIMIZATION_INCOMPLETE" and len(result.placements) == 1


def test_unsuccessful_results_carry_no_quality(snapshot):
    snapshot = scenario(snapshot, [{"lecturer_id": uid(20)}, {"lecturer_id": uid(20)}], window_minutes=100)
    result = solve_weekly_schedule(snapshot, None, PREFERENCES)
    assert not result.has_solution and result.quality is None and not result.quality_optimized
