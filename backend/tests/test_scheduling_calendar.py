import json
from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from backend.app.config import SchedulingSettings, load_settings
from backend.app.scheduling.calendar import TeachingCalendar


def calendar_settings(**overrides):
    payload = {
        "timezone": "Asia/Kuala_Lumpur",
        "opening_hours": {
            day: {"opens_at": "08:30", "closes_at": "18:00"}
            for day in ("monday", "tuesday", "wednesday", "thursday", "friday")
        },
        "closed_dates": [],
    }
    payload.update(overrides)
    return SchedulingSettings.model_validate(payload)


@pytest.mark.parametrize("start,end,expected", [
    ("2026-11-09T08:30:00+08:00", "2026-11-09T18:00:00+08:00", True),
    ("2026-11-09T09:17:23.123456+08:00", "2026-11-09T10:47:23.123456+08:00", True),
    ("2026-11-09T12:00:00+08:00", "2026-11-09T13:30:00+08:00", True),
    ("2026-11-09T08:29:59+08:00", "2026-11-09T10:00:00+08:00", False),
    ("2026-11-09T17:00:00+08:00", "2026-11-09T18:00:01+08:00", False),
    ("2026-11-09T18:00:00+08:00", "2026-11-09T18:00:00+08:00", False),
    ("2026-11-09T10:00:00+08:00", "2026-11-09T09:00:00+08:00", False),
    ("2026-11-09T17:00:00+08:00", "2026-11-10T09:00:00+08:00", False),
    ("2026-11-14T09:00:00+08:00", "2026-11-14T10:00:00+08:00", False),
    ("2026-11-15T09:00:00+08:00", "2026-11-15T10:00:00+08:00", False),
    ("2026-11-13T17:00:00+08:00", "2026-11-13T18:00:00+08:00", True),
    ("2026-11-09T00:30:00+00:00", "2026-11-09T10:00:00+00:00", True),
    ("2026-11-08T16:30:00+00:00", "2026-11-08T17:30:00+00:00", False),
])
def test_full_interval_uses_local_calendar_without_start_grid(start, end, expected):
    calendar = TeachingCalendar(calendar_settings())
    assert calendar.is_within_opening_hours(datetime.fromisoformat(start), datetime.fromisoformat(end)) is expected


def test_closure_overrides_teaching_weekday():
    calendar = TeachingCalendar(calendar_settings(closed_dates=["2026-11-09"]))
    assert calendar.opening_window(date(2026, 11, 9)) is None
    assert not calendar.is_within_opening_hours(
        datetime.fromisoformat("2026-11-09T10:00:00+08:00"),
        datetime.fromisoformat("2026-11-09T11:00:00+08:00"),
    )


def test_config_can_enable_weekend_and_different_daily_hours():
    calendar = TeachingCalendar(calendar_settings(opening_hours={
        "saturday": {"opens_at": "10:15", "closes_at": "14:45"},
    }))
    assert calendar.opening_window(date(2026, 11, 9)) is None
    assert calendar.is_within_opening_hours(
        datetime.fromisoformat("2026-11-14T10:15:00+08:00"),
        datetime.fromisoformat("2026-11-14T14:45:00+08:00"),
    )


@pytest.mark.parametrize("start,end", [
    (datetime(2026, 11, 9, 9), datetime(2026, 11, 9, 10, tzinfo=timezone.utc)),
    (datetime(2026, 11, 9, 9, tzinfo=timezone.utc), datetime(2026, 11, 9, 10)),
])
def test_rejects_timestamps_without_offsets(start, end):
    with pytest.raises(ValueError, match="timezone-aware"):
        TeachingCalendar(calendar_settings()).is_within_opening_hours(start, end)


@pytest.mark.parametrize("overrides", [
    {"timezone": "Not/A_Timezone"},
    {"opening_hours": {}},
    {"opening_hours": {"Monday": {"opens_at": "08:30", "closes_at": "18:00"}}},
    {"opening_hours": {"monday": {"opens_at": "8:30", "closes_at": "18:00"}}},
    {"opening_hours": {"monday": {"opens_at": "08:60", "closes_at": "18:00"}}},
    {"opening_hours": {"monday": {"opens_at": "08:30", "closes_at": "24:00"}}},
    {"opening_hours": {"monday": {"opens_at": "18:00", "closes_at": "08:30"}}},
    {"opening_hours": {"monday": {"opens_at": "08:30", "closes_at": "08:30"}}},
    {"closed_dates": ["2026-02-30"]},
    {"start_interval_minutes": 30},
])
def test_invalid_calendar_configuration_fails_validation(overrides):
    with pytest.raises(ValidationError):
        calendar_settings(**overrides)


def test_load_settings_rejects_invalid_scheduling_config(tmp_path):
    payload = load_settings().model_dump(mode="json")
    payload["scheduling"]["opening_hours"]["monday"]["closes_at"] = "07:00"
    path = tmp_path / "config.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValidationError, match="opens_at must be before closes_at"):
        load_settings(path)
