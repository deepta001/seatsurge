"""Adversarial test 14: rate limiting returns 429 with Retry-After and recovers after the window."""

import asyncio
from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.dependencies import get_redis
from app.core.settings import Settings, get_settings
from app.db.session import create_session_factory
from app.main import app
from app.redis.client import build_redis_client
from app.services.auth import register_user
from tests.sales import Sale, hold

WINDOW = 1.5  # seconds: short, so recovery can be watched in a test
PASSWORD = "a long enough password"


@pytest.fixture
def limits(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Small limits for this test only (the suite's defaults are huge)."""
    settings = get_settings()
    monkeypatch.setattr(settings, "rate_limit_window_seconds", WINDOW)
    monkeypatch.setattr(settings, "rate_limit_holds", 3)
    monkeypatch.setattr(settings, "rate_limit_login_per_email", 3)
    monkeypatch.setattr(settings, "rate_limit_login_per_ip", 5)
    return settings


@pytest.fixture
async def accounts(db_engine: AsyncEngine) -> list[str]:
    emails = []
    async with create_session_factory(db_engine)() as session:
        for n in range(1, 4):
            email = f"limited{n}@example.com"
            await register_user(session, email=email, username=f"limited{n}", password=PASSWORD)
            emails.append(email)
    return emails


async def login(client: AsyncClient, email: str, password: str = PASSWORD) -> int:
    response = await client.post("/auth/login", json={"email": email, "password": password})
    return response.status_code


async def test_holds_are_limited_per_user_and_recover_after_the_window(
    client: AsyncClient, sale: Sale, limits: Settings
) -> None:
    statuses = [(await hold(client, sale, user_id=1)).status_code for _ in range(3)]
    assert statuses == [201, 201, 201]

    refused = await hold(client, sale, user_id=1)

    assert (refused.status_code, refused.json()["error"]) == (429, "rate_limited")
    assert 1 <= int(refused.headers["Retry-After"]) <= 2
    assert (await hold(client, sale, user_id=2)).status_code == 201  # others unaffected
    await asyncio.sleep(WINDOW + 0.1)
    assert (await hold(client, sale, user_id=1)).status_code == 201  # recovered


async def test_a_burst_of_simultaneous_requests_lets_exactly_the_limit_through(
    client: AsyncClient, sale: Sale, limits: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(limits, "rate_limit_holds", 10)
    start = asyncio.Event()

    async def one() -> int:
        await start.wait()
        return (await hold(client, sale, user_id=1)).status_code

    tasks = [asyncio.create_task(one()) for _ in range(40)]
    start.set()
    statuses = await asyncio.gather(*tasks)

    assert statuses.count(429) == 30  # the script is atomic: not 31, not 29
    assert statuses.count(201) == 10


async def test_password_guessing_is_limited_per_email_and_recovers(
    client: AsyncClient, accounts: list[str], limits: Settings
) -> None:
    target, other, _ = accounts
    guesses = [await login(client, target, "wrong password!!") for _ in range(3)]
    assert guesses == [401, 401, 401]

    # Even the RIGHT password is refused now: the guesser can't tell it's correct.
    assert await login(client, target) == 429
    assert await login(client, other) == 200  # another account is unaffected
    await asyncio.sleep(WINDOW + 0.1)
    assert await login(client, target) == 200


async def test_logins_are_limited_per_ip_across_many_emails(
    client: AsyncClient, limits: Settings
) -> None:
    # Credential stuffing: one address trying many accounts.
    statuses = [await login(client, f"nobody{n}@example.com") for n in range(6)]

    assert statuses == [401, 401, 401, 401, 401, 429]


async def test_login_still_works_when_redis_is_down(
    client: AsyncClient, accounts: list[str], limits: Settings
) -> None:
    dead = build_redis_client("redis://:x@127.0.0.1:1/0", max_connections=2, pool_timeout_seconds=1)

    async def unreachable_redis() -> AsyncIterator[object]:
        yield dead

    app.dependency_overrides[get_redis] = unreachable_redis
    try:
        # The rate limit is skipped (and logged) rather than locking everyone out.
        assert await login(client, accounts[0]) == 200
    finally:
        await dead.aclose()


async def test_the_window_slides_one_request_at_a_time(
    client: AsyncClient, sale: Sale, limits: Settings
) -> None:
    """Not a fixed "reset every 1.5 s": each request leaves the window 1.5 s after it was made."""
    for _ in range(3):  # at t = 0, 0.6, 1.2: the limit of 3 is reached
        assert (await hold(client, sale, user_id=1)).status_code == 201
        await asyncio.sleep(0.6)

    # Now t is about 1.8: the first request has slid out, the other two are still in.
    assert (await hold(client, sale, user_id=1)).status_code == 201
    assert (await hold(client, sale, user_id=1)).status_code == 429
