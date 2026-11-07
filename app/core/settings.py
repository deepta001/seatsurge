"""Loads the app's configuration from environment variables and the .env file.

Everything configurable lives here, typed and validated, so the rest of the code
asks `get_settings()` instead of reading environment variables directly.
"""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All app configuration. Each field is filled from the env var of the same name (any case)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # .env also holds values for Docker (S0.7) that the app doesn't use.
        extra="ignore",
    )

    app_name: str = "seatsurge"
    environment: Literal["local", "test", "production"] = "local"

    # No defaults on purpose: the app refuses to start without them, so a
    # password can never be hard-coded in the source (CLAUDE.md section 9).
    # SecretStr prints as '**********' so the password never lands in logs.
    database_url: SecretStr
    redis_url: SecretStr


@lru_cache
def get_settings() -> Settings:
    """Build the Settings once and reuse that same object on every later call."""
    return Settings()  # type: ignore[call-arg]  # values come from the environment, not arguments
