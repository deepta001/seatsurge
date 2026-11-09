"""Loads the app's configuration from environment variables and the .env file.

Everything configurable lives here, typed and validated, so the rest of the code
asks `get_settings()` instead of reading environment variables directly.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
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
    # json: one JSON object per log line (containers, log tools); console:
    # easier for a human to read while developing (S8.2b).
    log_format: Literal["json", "console"] = "json"

    # No defaults on purpose: the app refuses to start without them, so a
    # password can never be hard-coded in the source (CLAUDE.md section 9).
    # SecretStr prints as '**********' so the password never lands in logs.
    database_url: SecretStr
    redis_url: SecretStr

    # Postgres connections per process: up to pool_size + max_overflow open at
    # once. All processes together must stay under Postgres's max_connections
    # (100): 3 api x 15 + worker 15 = 60 (docs/design.md, S8.1).
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_max_overflow: int = Field(default=10, ge=0, le=50)

    # The worker serves its Prometheus metrics on this port (internal network only).
    worker_metrics_port: int = Field(default=9100, ge=1024, le=65535)

    # Per process. Three API replicas use 3x this many Redis connections.
    redis_max_connections: int = Field(default=50, gt=0, le=1000)
    # How long a request waits for a free Redis connection before failing.
    redis_pool_timeout_seconds: float = Field(default=5.0, gt=0, le=60)

    # How long a hold keeps seats before they return to sale (CLAUDE.md rule 2).
    hold_ttl_seconds: int = Field(default=300, ge=30, le=3600)
    # The most seats one user may hold at once for one event.
    hold_user_cap: int = Field(default=10, ge=1, le=100)

    # The most tickets one user may BUY per event, across all their orders
    # (CLAUDE.md section 7.2). Enforced in Postgres at confirm time.
    purchase_user_cap: int = Field(default=10, ge=1, le=100)
    # How long a confirm may run past the hold's expiry before the sweeper
    # checks whether it ever produced an order.
    confirm_grace_seconds: int = Field(default=120, ge=10, le=3600)

    # Rate limits (CLAUDE.md sections 7.1 and 9): at most N requests per window.
    # Holds per user; logins per email address and per client IP.
    rate_limit_window_seconds: float = Field(default=60.0, gt=0, le=3600)
    rate_limit_holds: int = Field(default=20, ge=1)
    rate_limit_login_per_email: int = Field(default=5, ge=1)
    rate_limit_login_per_ip: int = Field(default=20, ge=1)

    # Mock payments only (there are no real payments in this project): the
    # chance that a valid "tok_ok" charge is randomly declined, for testing
    # failure paths. 0.0 = never, 1.0 = always.
    payment_failure_rate: float = Field(default=0.0, ge=0.0, le=1.0)

    # The largest request body the API will read. Every real request here is a
    # few hundred bytes; anything bigger is a mistake or an attack.
    max_request_body_bytes: int = Field(default=16 * 1024, ge=1024, le=1024 * 1024)

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

    # Browser front-ends allowed to call this API from another origin (CORS),
    # e.g. ["https://tickets.example.com"]. Empty = no cross-origin access.
    # Set as JSON in .env: CORS_ORIGINS=["https://tickets.example.com"].
    cors_origins: list[str] = Field(default_factory=list)

    @field_validator("cors_origins")
    @classmethod
    def no_wildcard_origin(cls, origins: list[str]) -> list[str]:
        # "*" would let any website call the API from a visitor's browser.
        if "*" in origins:
            raise ValueError("list the allowed origins explicitly; '*' is not allowed")
        return origins

    @field_validator("database_url", "redis_url", "jwt_secret_key")
    @classmethod
    def not_a_placeholder(cls, value: SecretStr) -> SecretStr:
        # .env.example ships CHANGE_ME placeholders; starting with one would
        # mean running with a password that is printed in the repository.
        if "CHANGE_ME" in value.get_secret_value():
            raise ValueError("still the CHANGE_ME placeholder from .env.example")
        return value


@lru_cache
def get_settings() -> Settings:
    """Build the Settings once and reuse that same object on every later call."""
    return Settings()  # type: ignore[call-arg]  # values come from the environment, not arguments
