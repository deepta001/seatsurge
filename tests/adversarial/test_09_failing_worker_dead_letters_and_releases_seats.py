"""Adversarial test 9: worker fails N times -> order FAILED, message dead-lettered, seats released.

Also: a failure that clears up is retried successfully, retries wait for
their backoff, a crashed worker's messages are rescued by another worker,
and dead-lettering never gives back the seats of an order that got tickets.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.redis import confirm_scripts
from app.redis.keys import (
    DEAD_LETTER_STREAM_KEY,
    HOLDS_CONFIRMING_KEY,
    ORDERS_STREAM_KEY,
    hold_key,
    inventory_key,
    user_hold_key,
)
from app.services.payments import MockPaymentProvider
from app.services.tickets import issue_tickets
from app.worker import handlers as handlers_module
from app.worker.consumer import ORDERS_GROUP, read_new_entries
from app.worker.handlers import build_compensations, build_handlers
from app.worker.messages import StreamMessage
from app.worker.retries import RedeliveryPolicy, retry_stuck
from tests.outbox import run_pipeline
from tests.sales import Sale, confirm, hold, stream_messages

# No waiting between retries, and give up after the 3rd failed delivery.
FAST = RedeliveryPolicy(max_deliveries=3, base_delay_ms=0)


class FlakyIssuer:
    """Stands in for issue_tickets: fails the first `failures` calls, then really issues."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    async def __call__(self, session: AsyncSession, order_id: Any) -> Any:
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("simulated: the database timed out")
        return await issue_tickets(session, order_id)


async def place_order(client: AsyncClient, sale: Sale, user_id: int, quantity: int) -> str:
    held = await hold(client, sale, user_id=user_id, quantity=quantity)
    assert held.status_code == 201
    assert (await confirm(client, held.json()["hold_id"], user_id)).status_code == 202
    return str(held.json()["hold_id"])


async def retry_until_settled(
    sessions: async_sessionmaker[AsyncSession], redis: Redis, policy: RedeliveryPolicy
) -> None:
    """Run retry passes until nothing is pending (or give up after 10 passes)."""
    for _ in range(10):
        if (await redis.xpending(ORDERS_STREAM_KEY, ORDERS_GROUP))["pending"] == 0:
            return
        await retry_stuck(
            redis,
            build_handlers(sessions, redis),
            build_compensations(sessions, redis),
            consumer="w2",
            policy=policy,
        )


async def one_value(db_engine: AsyncEngine, sql: str) -> Any:
    async with db_engine.connect() as conn:
        return await conn.scalar(text(sql))


async def test_a_worker_that_keeps_failing_dead_letters_the_order_and_releases_its_seats(
    client: AsyncClient,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
    redis: Redis,
    db_engine: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hold_id = await place_order(client, sale, buyers[0], quantity=3)
    assert await redis.get(inventory_key(sale.event_id, sale.tier_id)) == "47"
    issuer = FlakyIssuer(failures=99)  # never recovers
    monkeypatch.setattr(handlers_module, "issue_tickets", issuer)

    assert await run_pipeline(sessions, redis) == 0  # 1st delivery fails
    await retry_until_settled(sessions, redis, FAST)  # 2nd and 3rd fail; then it gives up

    assert issuer.calls == 3
    assert await one_value(db_engine, "SELECT status FROM orders") == "FAILED"
    assert await one_value(db_engine, "SELECT count(*) FROM tickets") == 0
    assert await one_value(db_engine, f"SELECT sold FROM tiers WHERE id = {sale.tier_id}") == 0
    # Dead-lettered with the reason and the original message...
    [dead] = await stream_messages(redis, DEAD_LETTER_STREAM_KEY)
    assert dead["dead_reason"] == "gave up after 3 failed deliveries"
    assert dead["deliveries"] == "3"
    assert dead["type"] == "order.placed"
    assert (await redis.xpending(ORDERS_STREAM_KEY, ORDERS_GROUP))["pending"] == 0
    # ...and NO leaked seats: all 3 are back, and the hold no longer counts.
    assert await redis.get(inventory_key(sale.event_id, sale.tier_id)) == "50"
    assert await redis.get(user_hold_key(sale.event_id, buyers[0])) is None
    assert await redis.hget(hold_key(hold_id), "status") == "RELEASED"
    assert await redis.zscore(HOLDS_CONFIRMING_KEY, hold_id) is None
    # The released seats can be held by someone else.
    assert (await hold(client, sale, user_id=buyers[1], quantity=10)).status_code == 201
    assert await redis.get(inventory_key(sale.event_id, sale.tier_id)) == "40"


async def test_a_failure_that_clears_up_is_retried_and_succeeds(
    client: AsyncClient,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
    redis: Redis,
    db_engine: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await place_order(client, sale, buyers[0], quantity=2)
    issuer = FlakyIssuer(failures=1)
    monkeypatch.setattr(handlers_module, "issue_tickets", issuer)

    assert await run_pipeline(sessions, redis) == 0
    await retry_until_settled(sessions, redis, FAST)

    assert issuer.calls == 2
    assert await one_value(db_engine, "SELECT status FROM orders") == "CONFIRMED"
    assert await one_value(db_engine, "SELECT count(*) FROM tickets") == 2
    assert await stream_messages(redis, DEAD_LETTER_STREAM_KEY) == []


async def test_a_retry_waits_for_its_backoff(
    client: AsyncClient,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
    redis: Redis,
    sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await place_order(client, sale, buyers[0], quantity=1)
    issuer = FlakyIssuer(failures=99)
    monkeypatch.setattr(handlers_module, "issue_tickets", issuer)
    await run_pipeline(sessions, redis)

    slow = RedeliveryPolicy(base_delay_ms=60_000)
    handled = await retry_stuck(
        redis,
        build_handlers(sessions, redis),
        build_compensations(sessions, redis),
        consumer="w2",
        policy=slow,
    )

    assert handled == 0
    assert issuer.calls == 1  # not tried again yet: its 60 s backoff hasn't passed
    [info] = await redis.xpending_range(ORDERS_STREAM_KEY, ORDERS_GROUP, "-", "+", 10)
    assert info["times_delivered"] == 1


async def test_messages_of_a_crashed_worker_are_rescued_by_another(
    client: AsyncClient,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
    redis: Redis,
    db_engine: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    from app.worker.consumer import ensure_group
    from app.worker.relay import relay_batch

    await place_order(client, sale, buyers[0], quantity=2)
    await relay_batch(sessions, redis)
    await ensure_group(redis)
    # Worker "w1" takes the message, then dies before handling it.
    taken = await read_new_entries(redis, "w1", 10, None, ORDERS_STREAM_KEY, ORDERS_GROUP)
    assert len(taken) == 1

    await retry_until_settled(sessions, redis, FAST)  # worker "w2" takes it over

    assert await one_value(db_engine, "SELECT status FROM orders") == "CONFIRMED"
    assert await one_value(db_engine, "SELECT count(*) FROM tickets") == 2


async def test_dead_lettering_never_releases_the_seats_of_an_order_with_tickets(
    client: AsyncClient,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
    redis: Redis,
    db_engine: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await place_order(client, sale, buyers[0], quantity=3)

    async def redis_step_always_fails(self: Any, *args: Any, **kwargs: Any) -> Any:
        raise ConnectionError("simulated: Redis keeps failing after the commit")

    # Tickets commit fine, but the after-commit Redis step fails every time.
    monkeypatch.setattr(confirm_scripts.FinishHoldScript, "__call__", redis_step_always_fails)
    await run_pipeline(sessions, redis)
    await retry_until_settled(sessions, redis, FAST)

    assert len(await stream_messages(redis, DEAD_LETTER_STREAM_KEY)) == 1
    # The order has its tickets, so it stays CONFIRMED and its seats stay sold.
    assert await one_value(db_engine, "SELECT status FROM orders") == "CONFIRMED"
    assert await one_value(db_engine, "SELECT count(*) FROM tickets") == 3
    assert await redis.get(inventory_key(sale.event_id, sale.tier_id)) == "47"


async def test_compensating_twice_releases_the_seats_once(
    client: AsyncClient,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
    redis: Redis,
    db_engine: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    hold_id = await place_order(client, sale, buyers[0], quantity=4)
    order_id = await one_value(db_engine, "SELECT id FROM orders")
    message = StreamMessage(
        entry_id="1-0",
        outbox_id=1,
        type="order.placed",
        aggregate_id=str(order_id),
        payload={"order_id": str(order_id), "hold_id": hold_id},
    )
    compensate = build_compensations(sessions, redis)["order.placed"]

    await compensate(message)
    await compensate(message)  # a dead-letter attempt that crashed and ran again

    assert await one_value(db_engine, "SELECT status FROM orders") == "FAILED"
    assert await redis.get(inventory_key(sale.event_id, sale.tier_id)) == "50"  # not 54


def test_backoff_doubles_up_to_the_cap() -> None:
    policy = RedeliveryPolicy(base_delay_ms=1000, max_delay_ms=5000)
    assert [policy.delay_ms(n) for n in range(1, 6)] == [1000, 2000, 4000, 5000, 5000]
