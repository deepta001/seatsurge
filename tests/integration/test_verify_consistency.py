"""scripts/verify_consistency.py: silent when all agrees, loud on every kind of mismatch."""

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.redis.client import build_redis_client
from app.redis.keys import inventory_key
from app.services.payments import MockPaymentProvider
from scripts import verify_consistency
from scripts.verify_consistency import verify, wait_until_drained
from tests.adversarial.test_09_failing_worker_dead_letters_and_releases_seats import place_order
from tests.outbox import run_pipeline
from tests.sales import Sale


@pytest.fixture
async def finished_sale(
    client: AsyncClient,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
    redis: Redis,
    sessions: async_sessionmaker[AsyncSession],
) -> Sale:
    """Three orders (2 + 3 + 1 seats), all fulfilled by the worker: a consistent state."""
    for buyer, quantity in zip(buyers, (2, 3, 1), strict=True):
        await place_order(client, sale, buyer, quantity)
    await run_pipeline(sessions, redis)
    return sale


async def test_a_finished_sale_is_consistent(
    finished_sale: Sale, redis: Redis, sessions: async_sessionmaker[AsyncSession]
) -> None:
    report = await verify(sessions, redis, finished_sale.event_id)
    assert report.problems == []
    assert (report.tiers_checked, report.tickets_issued, report.oversold) == (1, 6, 0)


async def test_a_sold_counter_that_disagrees_with_the_tickets_is_reported(
    finished_sale: Sale,
    redis: Redis,
    sessions: async_sessionmaker[AsyncSession],
    db_engine: AsyncEngine,
) -> None:
    async with db_engine.begin() as conn:
        await conn.execute(
            text("UPDATE tiers SET sold = sold - 1 WHERE id = :t"), {"t": finished_sale.tier_id}
        )
    report = await verify(sessions, redis, finished_sale.event_id)
    assert any("sold 5 but 6 ISSUED tickets" in p for p in report.problems)


async def test_a_redis_counter_that_disagrees_is_reported(
    finished_sale: Sale, redis: Redis, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await redis.incrby(inventory_key(finished_sale.event_id, finished_sale.tier_id), 3)
    report = await verify(sessions, redis, finished_sale.event_id)
    assert any("Redis counter 47, expected 44" in p for p in report.problems)


async def test_a_missing_redis_counter_is_reported_never_read_as_zero(
    finished_sale: Sale, redis: Redis, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await redis.delete(inventory_key(finished_sale.event_id, finished_sale.tier_id))
    report = await verify(sessions, redis, finished_sale.event_id)
    assert any("MISSING" in p for p in report.problems)


async def test_an_undrained_queue_is_reported(
    client: AsyncClient,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
    redis: Redis,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await place_order(client, sale, buyers[0], 1)  # confirmed, but the worker hasn't run
    assert await wait_until_drained(sessions, seconds=0) is False
    report = await verify(sessions, redis, sale.event_id)
    assert any("1 order(s) still PENDING" in p for p in report.problems)

    await run_pipeline(sessions, redis)
    assert await wait_until_drained(sessions, seconds=0) is True
    assert (await verify(sessions, redis, sale.event_id)).ok


async def test_the_command_exits_0_when_consistent_and_1_on_a_mismatch(
    finished_sale: Sale,
    redis: Redis,
    postgres_url: str,
    redis_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The command builds its own connections; point them at the test containers.
    monkeypatch.setattr(
        verify_consistency, "create_db_engine", lambda: create_async_engine(postgres_url)
    )
    monkeypatch.setattr(
        verify_consistency,
        "create_redis_client",
        lambda: build_redis_client(redis_url, max_connections=5, pool_timeout_seconds=5),
    )
    event = str(finished_sale.event_id)

    assert await verify_consistency.main(["--event", event, "--wait", "5"]) == 0
    assert "CONSISTENT" in capsys.readouterr().out

    await redis.decr(inventory_key(finished_sale.event_id, finished_sale.tier_id))
    assert await verify_consistency.main(["--event", event]) == 1
    output = capsys.readouterr().out
    assert "MISMATCH" in output and "INCONSISTENT: 1 problem(s)" in output
