"""Adversarial test 16: two workers on the same event don't conflict (no hot-row retries).

Every order for one tier updates the SAME `tiers` row (sold, next_number).
With two workers issuing tickets at once, that row must cause short waits
for its row lock, never errors, retries or lost updates: the update is one
atomic `UPDATE ... SET sold = sold + q WHERE sold + q <= capacity`, with no
read-modify-write and no ORM version column (rule 7).
"""

import asyncio
from collections import Counter

from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.redis.keys import DEAD_LETTER_STREAM_KEY, ORDERS_STREAM_KEY
from app.services.auth import register_user
from app.services.payments import MockPaymentProvider
from app.worker.consumer import ORDERS_GROUP, consume_batch, ensure_group
from app.worker.handlers import build_compensations, build_handlers
from app.worker.messages import StreamMessage
from app.worker.relay import relay_batch
from tests.adversarial.test_09_failing_worker_dead_letters_and_releases_seats import place_order
from tests.outbox import published_ids
from tests.sales import Sale, stream_messages

ORDERS = 30  # 10 buyers x 3 orders of 1 seat


async def query(engine: AsyncEngine, sql: str) -> list[tuple[object, ...]]:
    async with engine.connect() as conn:
        return [tuple(row) for row in (await conn.execute(text(sql))).all()]


async def test_two_workers_issue_one_events_tickets_without_conflicts(
    client: AsyncClient,
    sale: Sale,
    payments: MockPaymentProvider,
    redis: Redis,
    db_engine: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with sessions() as session:
        buyers = [
            (
                await register_user(
                    session,
                    email=f"w{n}@example.com",
                    username=f"w{n}",
                    password="a long password!",
                )
            ).id
            for n in range(10)
        ]
    for buyer in buyers:
        for _ in range(3):
            await place_order(client, sale, buyer, quantity=1)

    # Two relays at once: SKIP LOCKED lets each take different rows.
    start = asyncio.Event()

    async def relay() -> int:
        await start.wait()
        published = 0
        while batch := await relay_batch(sessions, redis, batch_size=4):
            published += batch
        return published

    relays = [asyncio.create_task(relay()) for _ in range(2)]
    start.set()
    published = await asyncio.gather(*relays)
    assert sum(published) == ORDERS
    assert sorted(await published_ids(redis)) == list(range(1, ORDERS + 1))  # each row ONCE

    # Two consumers at once, counting every time a message is handled.
    await ensure_group(redis)
    calls: Counter[int] = Counter()
    real = build_handlers(sessions, redis)["order.placed"]

    async def counting(message: StreamMessage) -> None:
        calls[message.outbox_id] += 1
        await real(message)

    handlers = {"order.placed": counting}
    compensations = build_compensations(sessions, redis)
    go = asyncio.Event()

    async def worker(name: str) -> int:
        await go.wait()
        acked = 0
        while handled := await consume_batch(
            redis, handlers, compensations, consumer=name, count=2, block_ms=None
        ):
            acked += handled
        return acked

    workers = [asyncio.create_task(worker(name)) for name in ("worker-a", "worker-b")]
    go.set()
    acked_a, acked_b = await asyncio.gather(*workers)

    # Both really worked, and every message was handled exactly once:
    # no failure, so no retry, no redelivery, no dead letter.
    assert acked_a > 0 and acked_b > 0
    assert acked_a + acked_b == ORDERS
    assert set(calls.values()) == {1} and len(calls) == ORDERS
    assert (await redis.xpending(ORDERS_STREAM_KEY, ORDERS_GROUP))["pending"] == 0
    assert await stream_messages(redis, DEAD_LETTER_STREAM_KEY) == []

    # The shared tier row got every update; ticket numbers are 1..30 with no gaps.
    [(sold, next_number)] = await query(
        db_engine, f"SELECT sold, next_number FROM tiers WHERE id = {sale.tier_id}"
    )
    assert (sold, next_number) == (ORDERS, ORDERS)
    numbers = [int(str(n)) for (n,) in await query(db_engine, "SELECT ticket_number FROM tickets")]
    assert sorted(numbers) == list(range(1, ORDERS + 1))
    assert await query(db_engine, "SELECT DISTINCT status FROM orders") == [("CONFIRMED",)]
