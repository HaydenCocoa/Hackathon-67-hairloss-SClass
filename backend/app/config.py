"""Load tracked boot configuration; user preferences are intentionally unused."""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

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


class Settings(SettingsModel):
    app: AppSettings
    server: ServerSettings
    supabase: SupabaseSettings


def load_settings(path: Path = PROJECT_ROOT / "Config" / "config.json") -> Settings:
    # Fail at startup with a useful validation error if required config is invalid.
    return Settings.model_validate(json.loads(path.read_text(encoding="utf-8")))
