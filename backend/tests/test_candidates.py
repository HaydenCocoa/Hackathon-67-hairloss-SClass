import random
from datetime import timedelta

import pytest
from pydantic import ValidationError

from backend.app.scheduling.candidates import CandidateGenerator, generate_candidates, generate_weekly_candidates
from backend.app.scheduling.loader import MeetingBooking
from backend.app.scheduling.validator import BookingProposal, BookingValidator
from backend.tests.test_booking_validator import (
    booking, change_requirement, instant, snapshot as sample_snapshot, uid, with_original,
)


@pytest.fixture
def snapshot(sample_snapshot):
    # One day keeps interval expectations small; other tests cover full-week loading.
    return sample_snapshot.model_copy(update={"opening_windows": sample_snapshot.opening_windows[:1]})


def ranges_for(result, room=1):
    return [(item.earliest_start, item.latest_start) for item in result.ranges if item.room_id == uid(room)]


def bounds(earliest, latest):
    return (instant(f"2026-11-09T{earliest}+08:00"), instant(f"2026-11-09T{latest}+08:00"))


def generate(snapshot, **options):
    return generate_candidates(snapshot, snapshot.requirements[0].occurrence_id, **options)


def test_complete_start_range_uses_only_suitable_rooms(snapshot):
    result = generate(snapshot)
    assert result.has_candidates
    assert {item.room_id for item in result.ranges} == {uid(1), uid(3)}
    assert ranges_for(result) == [bounds("08:30:00", "16:30:00")]
    assert ranges_for(result, 3) == [bounds("08:30:00", "16:30:00")]
    assert {item.code for item in result.diagnostics} >= {"ROOM_TYPE_MISMATCH", "ROOM_INACTIVE", "ROOM_TOO_SMALL"}
    assert result.snapshot_revision == snapshot.revision
    assert all(item.duration_minutes == 90 for item in result.ranges)


def test_two_hour_class_can_start_anywhere_in_the_range(snapshot):
    snapshot = change_requirement(snapshot, duration_minutes=120)
    window = snapshot.opening_windows[0].model_copy(update={"ends_at": instant("2026-11-09T12:00:00+08:00")})
    snapshot = snapshot.model_copy(update={"opening_windows": (window,)})
    result = generate(snapshot)
    assert ranges_for(result) == [bounds("08:30:00", "10:00:00")]
    candidate = next(item for item in result.ranges if item.room_id == uid(1))
    assert candidate.contains(instant("2026-11-09T09:17:23.123456+08:00"))
    assert candidate.contains(candidate.latest_start)
    assert not candidate.contains(candidate.latest_start + timedelta(microseconds=1))


def test_exact_fit_before_booking_is_a_single_start_instant(snapshot):
    snapshot = snapshot.model_copy(update={"class_bookings": (booking(room_id=uid(1)),)})
    result = generate(snapshot)
    assert ranges_for(result) == [bounds("08:30:00", "08:30:00"), bounds("11:30:00", "16:30:00")]
    assert ranges_for(result, 3) == [bounds("08:30:00", "16:30:00")]


@pytest.mark.parametrize("changes", [
    {"lecturer_id": uid(20)}, {"student_ids": frozenset([uid(10), uid(12)])},
])
def test_lecturer_or_cross_intake_student_booking_blocks_all_rooms(snapshot, changes):
    snapshot = snapshot.model_copy(update={"class_bookings": (booking(**changes),)})
    result = generate(snapshot)
    assert ranges_for(result) == ranges_for(result, 3) == [bounds("08:30:00", "08:30:00"), bounds("11:30:00", "16:30:00")]


def test_overlapping_nested_and_adjacent_busy_intervals_merge_before_subtraction(snapshot):
    fixed = tuple(booking(id=uid(80 + n), room_id=uid(1), start=f"2026-11-09T{start}+08:00", duration=duration)
                  for n, (start, duration) in enumerate([
                      ("09:00:00", 90), ("10:00:00", 90), ("11:30:00", 90), ("10:15:00", 30),
                  ]))
    snapshot = snapshot.model_copy(update={"class_bookings": tuple(reversed(fixed))})
    assert ranges_for(generate(snapshot)) == [bounds("13:00:00", "16:30:00")]


def test_bookings_are_clipped_to_the_window_and_preserve_full_class_duration(snapshot):
    fixed = (booking(id=uid(80), room_id=uid(1), start="2026-11-09T07:30:00+08:00", duration=180),
             booking(id=uid(81), room_id=uid(1), start="2026-11-09T17:00:00+08:00", duration=180))
    snapshot = snapshot.model_copy(update={"class_bookings": fixed})
    assert ranges_for(generate(snapshot)) == [bounds("10:30:00", "15:30:00")]


@pytest.mark.parametrize("microseconds", [0, 1])
def test_busy_end_at_opening_and_busy_start_at_closing_use_half_open_intervals(snapshot, microseconds):
    start = instant("2026-11-09T07:00:00+08:00") + timedelta(microseconds=microseconds)
    early = booking(id=uid(80), room_id=uid(1), start=start.isoformat(), duration=90)
    late = booking(id=uid(81), room_id=uid(1), start="2026-11-09T18:00:00+08:00")
    snapshot = snapshot.model_copy(update={"class_bookings": (early, late)})
    expected = instant("2026-11-09T08:30:00+08:00") + timedelta(microseconds=microseconds)
    assert ranges_for(generate(snapshot)) == [(expected, instant("2026-11-09T16:30:00+08:00"))]


def test_no_grid_or_duration_rounding_for_ninety_one_minutes(snapshot):
    snapshot = change_requirement(snapshot, duration_minutes=91)
    assert ranges_for(generate(snapshot)) == [bounds("08:30:00", "16:29:00")]


@pytest.mark.parametrize("condition,code", [
    ("closed", "NO_TEACHING_WINDOWS"), ("long", "DURATION_EXCEEDS_OPENING_WINDOWS"),
    ("no_rooms", "NO_ROOMS"), ("unknown_policy", "NO_SUITABLE_ROOMS"),
])
def test_empty_candidates_have_explicit_captured_scope_reasons(snapshot, condition, code):
    if condition == "closed":
        snapshot = snapshot.model_copy(update={"opening_windows": ()})
    elif condition == "long":
        snapshot = change_requirement(snapshot, duration_minutes=600)
    elif condition == "no_rooms":
        snapshot = snapshot.model_copy(update={"rooms": ()})
    else:
        snapshot = change_requirement(snapshot, course_type="others")
    result = generate(snapshot)
    assert not result.has_candidates
    assert code in {item.code for item in result.diagnostics}
    assert result.horizon_starts_at == snapshot.horizon_starts_at
    assert result.horizon_ends_at == snapshot.horizon_ends_at


def test_opening_window_outside_loaded_horizon_cannot_produce_candidates(snapshot):
    window = snapshot.opening_windows[0]
    window = window.model_copy(update={"starts_at": window.starts_at + timedelta(days=7), "ends_at": window.ends_at + timedelta(days=7)})
    snapshot = snapshot.model_copy(update={"opening_windows": (window,)})
    assert {item.code for item in generate(snapshot).diagnostics} == {"NO_TEACHING_WINDOWS"}


def test_fully_occupied_week_reports_supporting_booking_reasons_without_student_ids(snapshot):
    fixed = booking(start="2026-11-09T08:30:00+08:00", duration=570,
                    lecturer_id=uid(20), student_ids=frozenset([uid(10)]))
    snapshot = snapshot.model_copy(update={"class_bookings": (fixed,)})
    result = generate(snapshot)
    assert result.ranges == ()
    codes = {item.code for item in result.diagnostics}
    assert codes >= {"NO_VALID_START_RANGE", "LECTURER_CONFLICT", "STUDENT_CONFLICT"}
    assert any(item.booking_id == fixed.id and item.conflicting_student_count == 1 for item in result.diagnostics)
    assert str(uid(10)) not in result.model_dump_json()


def test_fragmented_free_time_is_not_mistaken_for_one_long_gap(snapshot):
    window = snapshot.opening_windows[0].model_copy(update={"ends_at": instant("2026-11-09T12:00:00+08:00")})
    fixed = tuple(booking(id=uid(80 + n), start=f"2026-11-09T{hour}:00:00+08:00", duration=30, lecturer_id=uid(20))
                  for n, hour in enumerate(["09", "10", "11"]))
    snapshot = snapshot.model_copy(update={"opening_windows": (window,), "class_bookings": fixed})
    assert not generate(snapshot).has_candidates


def test_cancelled_bookings_are_ignored(snapshot):
    fixed = booking(start="2026-11-09T08:30:00+08:00", duration=570, lecturer_id=uid(20))
    snapshot = snapshot.model_copy(update={"class_bookings": (fixed.model_copy(update={"status": "cancelled"}),)})
    assert ranges_for(generate(snapshot)) == [bounds("08:30:00", "16:30:00")]


def test_rescheduling_excludes_only_original_and_keeps_meetings_with_same_id(snapshot):
    snapshot = with_original(snapshot)
    assert {item.code for item in generate(snapshot).diagnostics} == {"ALREADY_SCHEDULED"}
    assert ranges_for(generate(snapshot, mode="reschedule")) == [bounds("08:30:00", "16:30:00")]
    meeting = MeetingBooking(id=snapshot.class_bookings[0].id, lecturer_id=uid(20), room_id=None,
                             starts_at=instant("2026-11-09T09:00:00+08:00"), ends_at=instant("2026-11-09T12:00:00+08:00"),
                             status="scheduled", student_ids=set())
    snapshot = snapshot.model_copy(update={"meeting_bookings": (meeting,)})
    assert ranges_for(generate(snapshot, mode="reschedule")) == [bounds("12:00:00", "16:30:00")]


def test_lifecycle_errors_match_validator_without_fabricating_start_times(snapshot):
    assert {item.code for item in generate(snapshot, mode="reschedule").diagnostics} == {"NOT_SCHEDULED"}
    cancelled = change_requirement(snapshot, requirement_status="cancelled", needs_scheduling=False)
    assert {item.code for item in generate(cancelled).diagnostics} == {"OCCURRENCE_CANCELLED"}
    missing = generate_candidates(snapshot, uid(999))
    assert not missing.has_candidates
    assert {item.code for item in missing.diagnostics} == {"OCCURRENCE_NOT_FOUND"}


def test_exhaustive_boundary_and_sample_agreement_with_single_booking_validator(snapshot):
    rng = random.Random(71)
    opening = snapshot.opening_windows[0].starts_at
    fixed = tuple(booking(
        id=uid(1000 + n), room_id=uid(rng.choice([1, 2, 3])), lecturer_id=uid(rng.choice([20, 21])),
        student_ids=frozenset([uid(rng.choice([10, 12]))]), duration=rng.choice([15, 30, 60, 90]),
        start=(opening + timedelta(seconds=rng.randint(-1800, 33000), microseconds=123456)).isoformat(),
    ) for n in range(9))
    snapshot = snapshot.model_copy(update={"class_bookings": fixed})
    result = generate(snapshot)
    validator = BookingValidator(snapshot)
    points = {opening + timedelta(seconds=seconds, microseconds=937) for seconds in range(-100, 35000, 137)}
    delta = timedelta(microseconds=1)
    for item in result.ranges:
        points.update([item.earliest_start, item.latest_start, item.earliest_start - delta, item.latest_start + delta])
    duration = timedelta(minutes=90)
    for item in fixed:
        points.update([item.starts_at - duration, item.starts_at - duration + delta, item.ends_at - delta, item.ends_at])
    for room in snapshot.rooms:
        for point in sorted(points):
            represented = any(item.room_id == room.id and item.contains(point) for item in result.ranges)
            checked = validator.validate(BookingProposal(occurrence_id=uid(100), room_id=room.id, starts_at=point))
            assert represented == checked.valid, (room.id, point, checked.reason_codes)


def test_weekly_generation_keeps_pending_lessons_independent_for_the_solver(snapshot):
    snapshot = with_original(snapshot)
    original = snapshot.requirements[0]
    pending = tuple(original.model_copy(update={
        "occurrence_id": uid(n), "class_session_id": None, "booking_status": None,
        "starts_at": None, "room_id": None, "needs_scheduling": True,
    }) for n in [201, 200])
    cancelled = original.model_copy(update={"occurrence_id": uid(202), "requirement_status": "cancelled", "needs_scheduling": False})
    window = snapshot.opening_windows[0].model_copy(update={"ends_at": instant("2026-11-09T10:00:00+08:00")})
    snapshot = snapshot.model_copy(update={"requirements": (original, *pending, cancelled), "opening_windows": (window,)})
    before = snapshot.model_dump_json()
    result = generate_weekly_candidates(snapshot)
    assert [item.occurrence_id for item in result.occurrences] == [uid(200), uid(201)]
    assert all(ranges_for(item) == [bounds("08:30:00", "08:30:00")] for item in result.occurrences)
    assert result.blocked_occurrence_ids == ()
    # Both can individually use this time; joint assignment remains step 7.
    assert snapshot.model_dump_json() == before


def test_empty_week_and_blocked_occurrence_summary(snapshot):
    empty = snapshot.model_copy(update={"requirements": ()})
    assert generate_weekly_candidates(empty).occurrences == ()
    blocked = change_requirement(snapshot, course_type="others")
    assert generate_weekly_candidates(blocked).blocked_occurrence_ids == (uid(100),)


def test_results_are_deterministic_immutable_and_reject_naive_contains(snapshot):
    generator = CandidateGenerator(snapshot)
    result = generator.generate(uid(100))
    assert result == generator.generate(uid(100))
    with pytest.raises(ValidationError):
        result.ranges[0].duration_minutes = 1
    with pytest.raises(ValueError, match="timezone offset"):
        result.ranges[0].contains(result.ranges[0].earliest_start.replace(tzinfo=None))
    with pytest.raises(ValidationError):
        generator.generate(uid(100), mode="ignore_conflicts")
