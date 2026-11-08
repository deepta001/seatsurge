"""Loads the app's configuration from environment variables and the .env file.

Everything configurable lives here, typed and validated, so the rest of the code
asks `get_settings()` instead of reading environment variables directly.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
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

    # Per process. Three API replicas use 3x this many Redis connections.
    redis_max_connections: int = Field(default=50, gt=0, le=1000)
    # How long a request waits for a free Redis connection before failing.
    redis_pool_timeout_seconds: float = Field(default=5.0, gt=0, le=60)

    # Signs access tokens. Anyone who knows it can forge a token for any user,
    # including an admin, so it lives only in .env. 32+ characters, so it can't
    # be guessed by brute force.
    jwt_secret_key: SecretStr = Field(min_length=32)
    # Short-lived on purpose: a stolen token stops working within minutes
    # (CLAUDE.md section 9). Refresh tokens (S1.5) keep users signed in.
    access_token_minutes: int = Field(default=15, gt=0, le=60)
    # How long a refresh token stays valid if unused. Each use replaces it
    # with a fresh one, so an active user stays signed in indefinitely.
    refresh_token_days: int = Field(default=7, gt=0, le=90)


@lru_cache
def get_settings() -> Settings:
    """Build the Settings once and reuse that same object on every later call."""
    return Settings()  # type: ignore[call-arg]  # values come from the environment, not arguments
