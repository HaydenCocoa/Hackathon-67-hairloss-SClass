"""Load tracked boot configuration; user preferences are intentionally unused."""

import json
from datetime import date
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def default_config_path() -> Path:
    """`Config/config.json` at the repository root is the only source of truth.

    A Vercel deployment bundles only `backend/`, so its build step copies that
    same file to `backend/Config/config.json` (see vercel.json). The repository
    copy wins whenever it exists, so local runs never read a stale build copy."""
    primary = PROJECT_ROOT / "Config" / "config.json"
    bundled = BACKEND_ROOT / "Config" / "config.json"
    return bundled if not primary.is_file() and bundled.is_file() else primary


class SettingsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AppSettings(SettingsModel):
    name: str = Field(min_length=1)
    description: str
    environment: str = Field(min_length=1)


class ServerSettings(SettingsModel):
    cors_origins: list[str]


class SupabaseSettings(SettingsModel):
    url_env: str = Field(min_length=1)
    key_env: str = Field(min_length=1)
    healthcheck_table: str = Field(pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    timeout_seconds: float = Field(gt=0, le=30)


Weekday = Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
WEEKDAYS: tuple[Weekday, ...] = (
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
)


class OpeningHours(SettingsModel):
    opens_at: str = Field(pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    closes_at: str = Field(pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")

    @model_validator(mode="after")
    def validate_order(self) -> "OpeningHours":
        if self.opens_at >= self.closes_at:
            raise ValueError("opens_at must be before closes_at within the same day")
        return self


CourseType = Literal["lecture", "tutorial", "lab", "others"]
RoomType = Literal["classroom", "lab", "auditorium"]


class SolverSettings(SettingsModel):
    max_time_seconds: float = Field(default=10.0, gt=0, allow_inf_nan=False)
    num_search_workers: int = Field(default=1, ge=1, le=32, strict=True)
    random_seed: int = Field(default=0, ge=0, le=2147483647, strict=True)


ObjectiveName = Literal["student_idle", "lecturer_idle", "room_fit"]


class QualityObjective(SettingsModel):
    name: ObjectiveName
    weight: int = Field(ge=0, le=1000, strict=True)


class QualitySettings(SettingsModel):
    """Step 8 preferences. They only rank valid timetables; compulsory rules never bend."""
    enabled: bool = Field(default=False, strict=True)
    objectives: list[QualityObjective] = Field(default_factory=list)

    @field_validator("objectives")
    @classmethod
    def unique_names(cls, value: list[QualityObjective]) -> list[QualityObjective]:
        if len({item.name for item in value}) != len(value):
            raise ValueError("Each quality objective may appear only once")
        return value

    def weight(self, name: ObjectiveName) -> int:
        return next((item.weight for item in self.objectives if item.name == name), 0)

    @property
    def active(self) -> bool:
        return self.enabled and any(item.weight > 0 for item in self.objectives)


class SchedulingSettings(SettingsModel):
    timezone: str = Field(min_length=1)
    opening_hours: dict[Weekday, OpeningHours] = Field(min_length=1)
    closed_dates: list[date] = Field(default_factory=list)
    room_compatibility: dict[CourseType, tuple[RoomType, ...]] = Field(default_factory=dict)
    # Compulsory: minutes that must separate two bookings sharing a room, lecturer or student.
    min_gap_minutes: int = Field(default=0, ge=0, le=240, strict=True)
    # Compulsory: these room types are used only when no other permitted room type has enough seats.
    reserved_room_types: tuple[RoomType, ...] = ()
    solver: SolverSettings = Field(default_factory=SolverSettings)
    quality: QualitySettings = Field(default_factory=QualitySettings)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("timezone must be an available IANA name, such as Asia/Kuala_Lumpur; install tzdata if missing") from exc
        return value


class Settings(SettingsModel):
    app: AppSettings
    server: ServerSettings
    supabase: SupabaseSettings
    scheduling: SchedulingSettings


def load_settings(path: Path | None = None) -> Settings:
    # Fail at startup with a useful validation error if required config is invalid.
    path = path if path is not None else default_config_path()
    return Settings.model_validate(json.loads(path.read_text(encoding="utf-8")))
