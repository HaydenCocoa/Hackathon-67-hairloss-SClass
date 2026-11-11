"""Configured teaching calendar with unrestricted class start times.

This checks calendar eligibility only. Availability also requires the later
booking validator to check lecturer, student, room, and reservation conflicts.
"""

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from ..config import SchedulingSettings, WEEKDAYS


class TeachingCalendar:
    def __init__(self, settings: SchedulingSettings):
        self._settings = settings.model_copy(deep=True)
        self._timezone = ZoneInfo(settings.timezone)

    def opening_window(self, day: date) -> tuple[datetime, datetime] | None:
        """Return the local day's opening interval, or None on a closed day."""
        if day in self._settings.closed_dates:
            return None
        hours = self._settings.opening_hours.get(WEEKDAYS[day.weekday()])
        if hours is None:
            return None
        return (
            datetime.combine(day, time.fromisoformat(hours.opens_at), self._timezone),
            datetime.combine(day, time.fromisoformat(hours.closes_at), self._timezone),
        )

    def is_within_opening_hours(self, starts_at: datetime, ends_at: datetime) -> bool:
        """Require the entire positive interval to fit in one opening window.

        Inputs must include an offset; their dates are interpreted in the
        configured timezone. No start-time grid, rounding, or breaks apply.
        """
        if any(value.utcoffset() is None for value in (starts_at, ends_at)):
            raise ValueError("starts_at and ends_at must be timezone-aware")
        start_utc = starts_at.astimezone(timezone.utc)
        end_utc = ends_at.astimezone(timezone.utc)
        if end_utc <= start_utc:
            return False
        window = self.opening_window(starts_at.astimezone(self._timezone).date())
        if window is None:
            return False
        opens_at, closes_at = window
        return opens_at.astimezone(timezone.utc) <= start_utc and end_utc <= closes_at.astimezone(timezone.utc)
