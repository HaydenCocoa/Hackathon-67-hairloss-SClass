from datetime import date, datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from backend.app.config import SchedulingSettings, load_settings
from backend.app.scheduling.loader import (
    ClassBooking, ClassRequirement, LecturerInput, MeetingBooking,
    OpeningWindow, RoomInput, RoomRule, SchedulingSnapshot,
)
from backend.app.scheduling.validator import BookingProposal, BookingValidator, validate_booking


def uid(number):
    return UUID(int=number)


def instant(value):
    return datetime.fromisoformat(value).astimezone(timezone.utc)


@pytest.fixture
def snapshot():
    settings = load_settings().scheduling
    requirement = ClassRequirement(
        occurrence_id=uid(100), plan_id=uid(101), section_id=uid(102),
        original_week_start=date(2026, 11, 9), target_week_start=date(2026, 11, 9),
        teaching_week_number=1, occurrence_number=1, requirement_status="required",
        timezone="Asia/Kuala_Lumpur", class_session_id=None, booking_status=None,
        starts_at=None, room_id=None, needs_scheduling=True,
        group_number=1, intake_id=uid(103), lecturer_id=uid(20),
        course_id=uid(104), course_code="TEST", course_name="Subject", course_type="lecture",
        duration_minutes=90, student_ids=frozenset([uid(10), uid(11)]),
    )
    rooms = tuple(RoomInput(id=uid(n), name=name, building="B", capacity=capacity, room_type=kind, is_active=active)
                  for n, name, capacity, kind, active in [
                      (1, "Classroom", 2, "classroom", True), (2, "Lab", 50, "lab", True),
                      (3, "Auditorium", 500, "auditorium", True), (4, "Closed", 1, "classroom", False),
                      (5, "Small", 1, "classroom", True),
                  ])
    windows = tuple(OpeningWindow(
        day=date(2026, 11, 9) + timedelta(days=offset),
        starts_at=instant("2026-11-09T08:30:00+08:00") + timedelta(days=offset),
        ends_at=instant("2026-11-09T18:00:00+08:00") + timedelta(days=offset),
    ) for offset in range(5))
    return SchedulingSnapshot(
        week_start=date(2026, 11, 9), timezone="Asia/Kuala_Lumpur",
        horizon_starts_at=instant("2026-11-09T00:00:00+08:00"),
        horizon_ends_at=instant("2026-11-16T00:00:00+08:00"),
        captured_at=instant("2026-11-09T00:00:00+08:00"), database_snapshot="test-snapshot", revision="a" * 64,
        opening_windows=windows, requirements=(requirement,), rooms=rooms,
        lecturers=(LecturerInput(id=uid(20)), LecturerInput(id=uid(21))),
        class_bookings=(), meeting_bookings=(),
        room_rules=tuple(RoomRule(course_type=kind, allowed_room_types=frozenset(allowed))
                         for kind, allowed in settings.room_compatibility.items()),
    )


def proposed(snapshot, at="2026-11-09T10:00:00+08:00", room=1, mode="schedule"):
    return BookingProposal(occurrence_id=snapshot.requirements[0].occurrence_id,
                           starts_at=at, room_id=uid(room), mode=mode)


def change_requirement(snapshot, **changes):
    return snapshot.model_copy(update={"requirements": (snapshot.requirements[0].model_copy(update=changes),)})


def booking(*, start="2026-11-09T10:00:00+08:00", duration=90, **changes):
    fields = dict(id=uid(60), occurrence_id=None, section_id=uid(61), intake_id=uid(62), group_number=1,
                  lecturer_id=uid(21), room_id=uid(2), starts_at=instant(start),
                  ends_at=instant(start) + timedelta(minutes=duration), duration_minutes=duration,
                  status="scheduled", student_ids=frozenset([uid(12)]))
    fields.update(changes)
    return ClassBooking(**fields)


def with_original(snapshot):
    original = booking(occurrence_id=snapshot.requirements[0].occurrence_id,
                       section_id=snapshot.requirements[0].section_id,
                       intake_id=snapshot.requirements[0].intake_id,
                       lecturer_id=uid(20), room_id=uid(1), student_ids=frozenset([uid(10), uid(11)]))
    snapshot = change_requirement(snapshot, class_session_id=original.id, booking_status="scheduled",
                                  starts_at=original.starts_at, room_id=original.room_id, needs_scheduling=False)
    return snapshot.model_copy(update={"class_bookings": (original,)})


@pytest.mark.parametrize("at", [
    "2026-11-09T08:30:00+08:00", "2026-11-09T09:17:00+08:00",
    "2026-11-09T12:00:00+08:00", "2026-11-09T16:30:00+08:00", "2026-11-09T01:17:00Z",
])
def test_valid_arbitrary_start_and_full_duration(snapshot, at):
    result = validate_booking(snapshot, proposed(snapshot, at))
    assert result.valid and result.issues == ()
    assert result.ends_at - result.starts_at == timedelta(minutes=90)
    assert result.snapshot_revision == snapshot.revision
    assert result.model_dump(mode="json")["valid"] is True


@pytest.mark.parametrize("at,code", [
    ("2026-11-09T08:29:00+08:00", "OUTSIDE_TEACHING_HOURS"),
    ("2026-11-09T16:31:00+08:00", "OUTSIDE_TEACHING_HOURS"),
    # Whole-minute starts (accepted 12 November 2026): any minute, but no seconds.
    ("2026-11-09T09:17:23.123456+08:00", "START_NOT_WHOLE_MINUTE"),
    ("2026-11-09T08:30:00.000001+08:00", "START_NOT_WHOLE_MINUTE"),
    ("2026-11-09T18:00:00+08:00", "OUTSIDE_TEACHING_HOURS"),
    ("2026-11-14T10:00:00+08:00", "OUTSIDE_TEACHING_HOURS"),
    ("2026-11-08T10:00:00+08:00", "OUTSIDE_HORIZON"),
    ("2026-11-16T10:00:00+08:00", "OUTSIDE_HORIZON"),
    ("2026-11-15T23:00:00+08:00", "OUTSIDE_HORIZON"),
])
def test_closed_days_and_full_interval_boundaries(snapshot, at, code):
    assert validate_booking(snapshot, proposed(snapshot, at)).reason_codes == (code,)


def test_explicit_closure_rejects_class_without_changing_start_grid(snapshot):
    snapshot = snapshot.model_copy(update={"opening_windows": snapshot.opening_windows[1:]})
    assert validate_booking(snapshot, proposed(snapshot)).reason_codes == ("OUTSIDE_TEACHING_HOURS",)


@pytest.mark.parametrize("kind,room,expected", [
    ("lecture", 1, True), ("lecture", 3, True), ("lecture", 2, False),
    ("tutorial", 1, True), ("tutorial", 2, True), ("tutorial", 3, False),
    ("lab", 1, True), ("lab", 2, True), ("lab", 3, False),
])
def test_confirmed_course_to_room_policy(snapshot, kind, room, expected):
    snapshot = change_requirement(snapshot, course_type=kind)
    result = validate_booking(snapshot, proposed(snapshot, room=room))
    assert result.valid is expected
    assert result.reason_codes == (() if expected else ("ROOM_TYPE_MISMATCH",))


def test_legacy_required_room_type_does_not_override_system_policy(snapshot):
    snapshot = change_requirement(snapshot, course_type="lab", required_room_type="lab")
    assert validate_booking(snapshot, proposed(snapshot, room=1)).valid


@pytest.mark.parametrize("rules", [(), (RoomRule(course_type="others", allowed_room_types=frozenset()),)])
def test_unknown_or_empty_room_policy_fails_explicitly(snapshot, rules):
    snapshot = change_requirement(snapshot, course_type="others", required_room_type="classroom")
    snapshot = snapshot.model_copy(update={"room_rules": rules})
    assert validate_booking(snapshot, proposed(snapshot)).reason_codes == ("ROOM_POLICY_UNDEFINED",)


def test_explicit_other_course_mapping_is_supported(snapshot):
    snapshot = change_requirement(snapshot, course_type="others")
    snapshot = snapshot.model_copy(update={"room_rules": (RoomRule(course_type="others", allowed_room_types={"classroom"}),)})
    assert validate_booking(snapshot, proposed(snapshot)).valid


@pytest.mark.parametrize("room,codes", [(999, ("ROOM_NOT_FOUND",)), (4, ("ROOM_INACTIVE", "ROOM_TOO_SMALL")), (5, ("ROOM_TOO_SMALL",))])
def test_room_identity_activity_and_actual_capacity(snapshot, room, codes):
    result = validate_booking(snapshot, proposed(snapshot, room=room))
    assert result.reason_codes == codes
    assert not result.valid


@pytest.mark.parametrize("changes,codes,count", [
    ({"lecturer_id": uid(20)}, ("LECTURER_CONFLICT",), 0),
    ({"student_ids": frozenset([uid(10), uid(12)])}, ("STUDENT_CONFLICT",), 1),
    ({"room_id": uid(1)}, ("ROOM_CONFLICT",), 0),
    ({"lecturer_id": uid(20), "room_id": uid(1), "student_ids": frozenset([uid(10), uid(11), uid(12)])},
     ("LECTURER_CONFLICT", "STUDENT_CONFLICT", "ROOM_CONFLICT"), 2),
])
def test_all_applicable_class_conflicts_are_reported(snapshot, changes, codes, count):
    fixed = booking(**changes)
    snapshot = snapshot.model_copy(update={"class_bookings": (fixed,)})
    result = validate_booking(snapshot, proposed(snapshot))
    assert result.reason_codes == codes
    assert all(issue.booking_id == fixed.id and issue.booking_kind == "class" for issue in result.issues)
    assert sum(issue.conflicting_student_count for issue in result.issues) == count
    assert str(uid(10)) not in result.model_dump_json()


def test_same_intake_with_disjoint_students_is_not_a_student_conflict(snapshot):
    fixed = booking(intake_id=snapshot.requirements[0].intake_id)
    snapshot = snapshot.model_copy(update={"class_bookings": (fixed,)})
    assert validate_booking(snapshot, proposed(snapshot)).valid


@pytest.mark.parametrize("start", ["2026-11-09T08:30:00+08:00", "2026-11-09T11:30:00+08:00"])
def test_adjacent_bookings_do_not_overlap_or_require_breaks(snapshot, start):
    fixed = booking(start=start, lecturer_id=uid(20), room_id=uid(1), student_ids=frozenset([uid(10), uid(11)]))
    snapshot = snapshot.model_copy(update={"class_bookings": (fixed,)})
    assert validate_booking(snapshot, proposed(snapshot)).valid


def test_even_one_microsecond_of_overlap_is_a_conflict(snapshot):
    fixed = booking(start="2026-11-09T11:29:59.999999+08:00", room_id=uid(1))
    snapshot = snapshot.model_copy(update={"class_bookings": (fixed,)})
    assert validate_booking(snapshot, proposed(snapshot)).reason_codes == ("ROOM_CONFLICT",)


@pytest.mark.parametrize("online", [True, False])
def test_meeting_attendance_and_online_room_behavior(snapshot, online):
    meeting = MeetingBooking(id=uid(70), lecturer_id=uid(20), room_id=None if online else uid(1),
                             starts_at=instant("2026-11-09T10:00:00+08:00"),
                             ends_at=instant("2026-11-09T10:30:00+08:00"),
                             status="scheduled", student_ids={uid(10)})
    snapshot = snapshot.model_copy(update={"meeting_bookings": (meeting,)})
    result = validate_booking(snapshot, proposed(snapshot))
    assert result.reason_codes == ("LECTURER_CONFLICT", "STUDENT_CONFLICT") + (() if online else ("ROOM_CONFLICT",))
    assert all(issue.booking_kind == "meeting" for issue in result.issues)


def test_cancelled_booking_does_not_block_availability(snapshot):
    fixed = booking(lecturer_id=uid(20), room_id=uid(1), student_ids=frozenset([uid(10)]))
    # The real loader already excludes these; exercise the validator's defensive guard.
    snapshot = snapshot.model_copy(update={"class_bookings": (fixed.model_copy(update={"status": "cancelled"}),)})
    assert validate_booking(snapshot, proposed(snapshot)).valid


def test_rescheduled_booking_blocks_like_a_scheduled_one(snapshot):
    fixed = booking(lecturer_id=uid(20), room_id=uid(1), student_ids=frozenset([uid(10)]), status="rescheduled")
    snapshot = snapshot.model_copy(update={"class_bookings": (fixed,)})
    assert validate_booking(snapshot, proposed(snapshot)).reason_codes == (
        "LECTURER_CONFLICT", "STUDENT_CONFLICT", "ROOM_CONFLICT")


def test_rescheduled_occurrence_is_booked_and_can_be_moved_again(snapshot):
    snapshot = with_original(snapshot)
    original = snapshot.class_bookings[0].model_copy(update={"status": "rescheduled"})
    snapshot = change_requirement(snapshot, booking_status="rescheduled")
    snapshot = snapshot.model_copy(update={"class_bookings": (original,)})
    assert validate_booking(snapshot, proposed(snapshot)).reason_codes == ("ALREADY_SCHEDULED",)
    assert validate_booking(snapshot, proposed(snapshot, mode="reschedule")).valid


def test_rescheduling_ignores_only_matching_original_class(snapshot):
    snapshot = with_original(snapshot)
    assert validate_booking(snapshot, proposed(snapshot)).reason_codes == ("ALREADY_SCHEDULED",)
    assert validate_booking(snapshot, proposed(snapshot, mode="reschedule")).valid
    other = booking(id=uid(71), occurrence_id=None, room_id=uid(1))
    snapshot = snapshot.model_copy(update={"class_bookings": (*snapshot.class_bookings, other)})
    assert validate_booking(snapshot, proposed(snapshot, mode="reschedule")).reason_codes == ("ROOM_CONFLICT",)


def test_reschedule_exclusion_does_not_skip_meeting_with_same_uuid(snapshot):
    snapshot = with_original(snapshot)
    meeting = MeetingBooking(id=snapshot.class_bookings[0].id, lecturer_id=uid(21), room_id=uid(1),
                             starts_at=instant("2026-11-09T10:00:00+08:00"),
                             ends_at=instant("2026-11-09T11:00:00+08:00"), status="scheduled", student_ids=set())
    snapshot = snapshot.model_copy(update={"meeting_bookings": (meeting,)})
    result = validate_booking(snapshot, proposed(snapshot, mode="reschedule"))
    assert result.reason_codes == ("ROOM_CONFLICT",)
    assert result.issues[0].booking_kind == "meeting"


def test_lifecycle_and_missing_occurrence_rejections(snapshot):
    assert validate_booking(snapshot, proposed(snapshot, mode="reschedule")).reason_codes == ("NOT_SCHEDULED",)
    cancelled = change_requirement(snapshot, requirement_status="cancelled", needs_scheduling=False)
    assert validate_booking(cancelled, proposed(cancelled)).reason_codes == ("OCCURRENCE_CANCELLED",)
    missing = proposed(snapshot).model_copy(update={"occurrence_id": uid(999)})
    result = validate_booking(snapshot, missing)
    assert result.reason_codes == ("OCCURRENCE_NOT_FOUND",) and result.ends_at is None
    broken = with_original(snapshot).model_copy(update={"class_bookings": ()})
    assert validate_booking(broken, proposed(broken, mode="reschedule")).reason_codes == ("ORIGINAL_BOOKING_NOT_FOUND",)


def test_explicitly_reopened_cancelled_booking_can_be_placed_again(snapshot):
    snapshot = change_requirement(snapshot, class_session_id=uid(60), booking_status="cancelled",
                                  starts_at=instant("2026-11-09T10:00:00+08:00"), room_id=uid(1))
    assert validate_booking(snapshot, proposed(snapshot)).valid


@pytest.mark.parametrize("extra", [
    {"ends_at": "2026-11-09T10:01:00+08:00"}, {"lecturer_id": str(uid(999))},
    {"student_ids": []}, {"exclude_booking_id": str(uid(60))}, {"mode": "ignore_conflicts"},
])
def test_proposals_cannot_override_trusted_resources_or_exclusions(snapshot, extra):
    payload = proposed(snapshot).model_dump(mode="json")
    payload.update(extra)
    with pytest.raises(ValidationError):
        BookingProposal.model_validate(payload)


def test_naive_start_is_rejected_and_results_do_not_mutate_input(snapshot):
    with pytest.raises(ValidationError, match="timezone offset"):
        BookingProposal(occurrence_id=uid(100), room_id=uid(1), starts_at=datetime(2026, 11, 9, 10))
    before = snapshot.model_dump_json()
    validator = BookingValidator(snapshot)
    first = validator.validate(proposed(snapshot))
    assert first == validator.validate(proposed(snapshot))
    assert snapshot.model_dump_json() == before
    with pytest.raises(ValidationError):
        first.issues = ()


@pytest.mark.parametrize("mapping", [{"seminar": ["classroom"]}, {"lecture": ["lecture_hall"]}])
def test_unknown_policy_types_fail_configuration_validation(mapping):
    payload = load_settings().scheduling.model_dump(mode="json")
    payload["room_compatibility"] = mapping
    with pytest.raises(ValidationError):
        SchedulingSettings.model_validate(payload)
