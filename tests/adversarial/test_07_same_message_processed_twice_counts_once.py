"""Adversarial test 7: the worker gets the same stream message twice; the work happens once.

The first tests use a small handler that adds the order's quantity to the
tier's `sold` counter (run twice, it would count the seats twice). The last
one runs the real ticket-issuing pipeline (S4.5).
"""

import asyncio
import json

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.redis.keys import ORDERS_STREAM_KEY
from app.services.payments import MockPaymentProvider
from app.worker.consumer import StreamMessage, consume_batch, ensure_group
from app.worker.idempotency import run_once
from tests.outbox import run_pipeline
from tests.sales import Sale, confirm, hold, stream_messages


async def publish(redis: Redis, outbox_id: int, sale: Sale, quantity: int) -> None:
    """Put one copy of outbox message `outbox_id` on the stream (call twice for a duplicate)."""
    payload = {"tier_id": sale.tier_id, "quantity": quantity}
    fields = {
        "outbox_id": str(outbox_id),
        "type": "order.placed",
        "aggregate_id": f"order-{outbox_id}",
        "payload": json.dumps(payload),
    }
    await redis.xadd(ORDERS_STREAM_KEY, fields)  # type: ignore[arg-type]


class CountSold:
    """Adds each message's quantity to its tier's `sold` counter, in the given session."""

    def __init__(self, fail_times: int = 0) -> None:
        self.calls = 0
        self.fail_times = fail_times

    async def __call__(self, session: AsyncSession, message: StreamMessage) -> None:
        self.calls += 1
        await session.execute(
            text("UPDATE tiers SET sold = sold + :q WHERE id = :t"),
            {"q": message.payload["quantity"], "t": message.payload["tier_id"]},
        )
        if self.calls <= self.fail_times:
            # Fails AFTER its write: that write must roll back with the claim.
            raise RuntimeError("simulated crash after the write")


async def sold(db_engine: AsyncEngine, sale: Sale) -> int:
    async with db_engine.connect() as conn:
        value = await conn.scalar(text("SELECT sold FROM tiers WHERE id = :t"), {"t": sale.tier_id})
        return int(value)


async def processed_ids(db_engine: AsyncEngine) -> list[int]:
    async with db_engine.connect() as conn:
        rows = await conn.scalars(text("SELECT message_id FROM processed_messages ORDER BY 1"))
        return list(rows)


@pytest.fixture
async def group(redis: Redis) -> None:
    await ensure_group(redis)


async def test_a_duplicate_message_is_skipped_and_acked(
    sale: Sale,
    redis: Redis,
    db_engine: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
    group: None,
) -> None:
    await publish(redis, 7, sale, quantity=2)
    await publish(redis, 7, sale, quantity=2)  # the relay published it again
    await publish(redis, 8, sale, quantity=3)  # a different order
    handler = CountSold()
    handlers = {"order.placed": run_once(sessions, handler)}

    assert await consume_batch(redis, handlers, consumer="w1", block_ms=None) == 3

    assert await sold(db_engine, sale) == 2 + 3  # not 2 + 2 + 3
    assert handler.calls == 2  # the duplicate never reached the handler
    assert await processed_ids(db_engine) == [7, 8]
    pending = await redis.xpending(ORDERS_STREAM_KEY, "order-workers")
    assert pending["pending"] == 0  # the duplicate was acked, not left to retry forever


async def test_simultaneous_duplicates_on_different_workers_count_once(
    sale: Sale,
    redis: Redis,
    db_engine: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
    group: None,
) -> None:
    for _ in range(12):
        await publish(redis, 7, sale, quantity=2)
    handler = CountSold()
    handlers = {"order.placed": run_once(sessions, handler)}
    start = asyncio.Event()

    async def worker(name: str) -> int:
        await start.wait()  # all workers begin together
        return await consume_batch(redis, handlers, consumer=name, count=4, block_ms=None)

    tasks = [asyncio.create_task(worker(f"w{n}")) for n in range(3)]
    start.set()
    acked = await asyncio.gather(*tasks)

    assert sum(acked) == 12
    assert await sold(db_engine, sale) == 2
    assert handler.calls == 1


async def test_if_the_work_fails_the_claim_rolls_back_too(
    sale: Sale,
    redis: Redis,
    db_engine: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
    group: None,
) -> None:
    handler = CountSold(fail_times=1)
    handlers = {"order.placed": run_once(sessions, handler)}

    await publish(redis, 7, sale, quantity=2)
    assert await consume_batch(redis, handlers, consumer="w1", block_ms=None) == 0
    # Nothing half-done: no seats counted, and no "processed" mark either...
    assert await sold(db_engine, sale) == 0
    assert await processed_ids(db_engine) == []

    # ...so when the message comes again (S4.6 will redeliver it), the work happens.
    await publish(redis, 7, sale, quantity=2)
    assert await consume_batch(redis, handlers, consumer="w1", block_ms=None) == 1
    assert await sold(db_engine, sale) == 2
    assert await processed_ids(db_engine) == [7]


async def test_a_duplicate_order_message_issues_its_tickets_once(
    client: AsyncClient,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
    redis: Redis,
    db_engine: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    held = await hold(client, sale, user_id=buyers[0], quantity=3)
    assert (await confirm(client, held.json()["hold_id"], buyers[0])).status_code == 202
    await run_pipeline(sessions, redis)

    # The relay publishes the same outbox row again (it crashed before marking it).
    [fields] = await stream_messages(redis, ORDERS_STREAM_KEY)
    await redis.xadd(ORDERS_STREAM_KEY, fields)  # type: ignore[arg-type]
    assert await run_pipeline(sessions, redis) == 1  # handled (skipped) and acked

    async with db_engine.connect() as conn:
        tickets = await conn.scalar(text("SELECT count(*) FROM tickets"))
    assert tickets == 3  # not 6
    assert await sold(db_engine, sale) == 3
