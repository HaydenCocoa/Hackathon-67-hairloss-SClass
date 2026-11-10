"""Load tracked boot configuration; user preferences are intentionally unused."""

import json
from datetime import date
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PROJECT_ROOT = Path(__file__).resolve().parents[2]


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


class SchedulingSettings(SettingsModel):
    timezone: str = Field(min_length=1)
    opening_hours: dict[Weekday, OpeningHours] = Field(min_length=1)
    closed_dates: list[date] = Field(default_factory=list)

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


def load_settings(path: Path = PROJECT_ROOT / "Config" / "config.json") -> Settings:
    # Fail at startup with a useful validation error if required config is invalid.
    return Settings.model_validate(json.loads(path.read_text(encoding="utf-8")))
