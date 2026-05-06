"""Application configuration loaded from environment variables.

Uses pydantic-settings for type-safe, validated config. All sensitive values
(API keys, DB URLs) come from the environment so the codebase is safe to commit.
"""

from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized typed settings for the backend."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- OpenAI ----
    openai_api_key: str = Field(default="", description="OpenAI API key")
    openai_realtime_model: str = "gpt-4o-realtime-preview-2024-12-17"
    openai_summary_model: str = "gpt-4o-mini"
    openai_realtime_voice: str = "sage"

    # ---- Server ----
    host: str = "0.0.0.0"
    port: int = 8000
    env: str = "development"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # ---- DB ----
    database_url: str = "sqlite+aiosqlite:///./mykare.db"

    # ---- Clinic ----
    clinic_name: str = "Mykare Health"
    clinic_timezone: str = "Asia/Kolkata"
    clinic_providers: str = "Dr. Aisha Khan,Dr. Rohan Mehta,Dr. Priya Sharma"

    # ---- Cost ----
    cost_audio_input_per_min: float = 0.06
    cost_audio_output_per_min: float = 0.24
    cost_text_input_per_1k: float = 0.005
    cost_text_output_per_1k: float = 0.020

    @property
    def allowed_origins(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def providers(self) -> List[str]:
        return [p.strip() for p in self.clinic_providers.split(",") if p.strip()]

    @field_validator("openai_api_key")
    @classmethod
    def warn_missing_key(cls, v: str) -> str:
        # We don't hard-fail at import time so docs / health endpoints still work
        # in dev. The /voice route will raise a friendly error if the key is missing.
        return v


@lru_cache
def get_settings() -> Settings:
    """Cached accessor so we only parse env once."""
    return Settings()
