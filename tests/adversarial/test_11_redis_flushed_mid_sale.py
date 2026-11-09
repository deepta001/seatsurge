"""Adversarial test 11: Redis is flushed mid-sale. No oversell, and reconcile restores everything.

A flush wipes every counter, hold, idempotency key, the order stream and the
worker's consumer group. Postgres still knows what was sold and which orders
are PENDING; that has to be enough to carry on safely.
"""

import asyncio
from typing import Any

from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.tokens import create_access_token
from app.db.models import UserRole
from app.redis.keys import DEAD_LETTER_STREAM_KEY, inventory_key
from app.redis.rehydrate import active_holds
from app.services.payments import MockPaymentProvider
from app.worker.consumer_loop import run_consumer
from app.worker.handlers import build_compensations, build_handlers
from app.worker.relay import relay_batch
from tests.outbox import run_pipeline
from tests.sales import Sale, confirm, hold, stream_messages

CAPACITY = 50


async def make_users(db_engine: AsyncEngine, count: int) -> list[int]:
    """Real user rows (orders need them), inserted directly to keep the test fast."""
    async with db_engine.begin() as conn:
        rows = await conn.scalars(
            text(
                "INSERT INTO users (email, username, password_hash) "
                "SELECT 'flush' || n || '@example.com', 'flush' || n, 'x' "
                "FROM generate_series(1, :count) AS n RETURNING id"
            ),
            {"count": count},
        )
        return list(rows)


async def one_value(db_engine: AsyncEngine, sql: str) -> Any:
    async with db_engine.connect() as conn:
        return await conn.scalar(text(sql))


async def counter(redis: Redis, sale: Sale) -> int | None:
    value = await redis.get(inventory_key(sale.event_id, sale.tier_id))
    return None if value is None else int(value)


async def live_held(redis: Redis, sale: Sale) -> int:
    return sum((await active_holds(redis, sale.event_id, sale.tier_id)).values())


async def test_a_flush_mid_sale_never_oversells_and_reconcile_restores_everything(
    client: AsyncClient,
    sale: Sale,
    payments: MockPaymentProvider,
    redis: Redis,
    db_engine: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    users = await make_users(db_engine, 10)
    a, b, c, rushers = users[0], users[1], users[2], users[3:]

    # Before the flush: A bought 6 (tickets issued), B confirmed 5 (published,
    # not processed yet), C holds 4.
    held_a = await hold(client, sale, user_id=a, quantity=6)
    await confirm(client, held_a.json()["hold_id"], a)
    await run_pipeline(sessions, redis)
    held_b = await hold(client, sale, user_id=b, quantity=5)
    await confirm(client, held_b.json()["hold_id"], b)
    await relay_batch(sessions, redis)  # B's message is on the stream...
    held_c = await hold(client, sale, user_id=c, quantity=4)
    assert await counter(redis, sale) == CAPACITY - 6 - 5 - 4

    await redis.flushdb()  # ...and now it's gone, along with everything else

    # C's hold no longer exists, so it can't be bought.
    assert (await confirm(client, held_c.json()["hold_id"], c)).status_code == 404

    # A rush: 7 users x 8 requests for 1 seat. The counter is rebuilt from
    # Postgres: 50 - 6 sold - 5 pending (B) = 39. C's lost hold is free again.
    start = asyncio.Event()

    async def buyer(user_id: int) -> str | None:
        await start.wait()
        response = await hold(client, sale, user_id=user_id, quantity=1)
        if response.status_code == 201:
            return str(response.json()["hold_id"])
        assert response.json()["error"] in ("sold_out", "hold_limit_exceeded")
        return None

    tasks = [asyncio.create_task(buyer(u)) for u in rushers for _ in range(8)]
    start.set()
    results = await asyncio.gather(*tasks)
    won = [(hold_id, rushers[i // 8]) for i, hold_id in enumerate(results) if hold_id]
    assert len(won) == CAPACITY - 6 - 5  # exactly 39: not one more
    assert await counter(redis, sale) == 0

    # The worker's stream was wiped, so B is stuck PENDING...
    await run_pipeline(sessions, redis)
    assert await one_value(db_engine, f"SELECT status FROM orders WHERE user_id = {b}") == "PENDING"

    # ...until an admin reconciles: counters re-checked, B's message re-sent.
    admin = {"Authorization": f"Bearer {create_access_token(sale.admin_id, UserRole.ADMIN)}"}
    response = await client.post(f"/admin/events/{sale.event_id}/reconcile", headers=admin)
    assert response.json()["requeued_orders"] == 1
    assert response.json()["tiers"][0]["after"] == 0
    await run_pipeline(sessions, redis)
    assert (
        await one_value(db_engine, f"SELECT status FROM orders WHERE user_id = {b}") == "CONFIRMED"
    )

    # Everyone who won a seat in the rush buys it.
    for hold_id, user_id in won:
        assert (await confirm(client, hold_id, user_id)).status_code == 202
    await run_pipeline(sessions, redis)

    # Sold out exactly, every ticket number once, nothing refused by the backstop.
    assert await one_value(db_engine, f"SELECT sold FROM tiers WHERE id = {sale.tier_id}") == 50
    assert await one_value(db_engine, "SELECT count(*) FROM tickets") == 50
    numbers = await one_value(db_engine, "SELECT count(DISTINCT ticket_number) FROM tickets")
    assert numbers == 50
    assert (
        await one_value(db_engine, "SELECT count(*) FROM orders WHERE status <> 'CONFIRMED'") == 0
    )
    assert await stream_messages(redis, DEAD_LETTER_STREAM_KEY) == []
    # And Redis agrees with Postgres.
    assert await counter(redis, sale) == 0
    assert await live_held(redis, sale) == 0


async def test_a_flush_during_a_rush_never_invents_seats(
    client: AsyncClient, sale: Sale, redis: Redis
) -> None:
    start = asyncio.Event()

    async def buyer(user_id: int) -> None:
        await start.wait()
        await hold(client, sale, user_id=user_id, quantity=1)

    async def flush_midway() -> None:
        await start.wait()
        await asyncio.sleep(0.05)  # some holds have gone through by now
        await redis.flushdb()

    tasks = [asyncio.create_task(buyer(n)) for n in range(1, 101)]  # 100 buyers, 50 seats
    tasks.append(asyncio.create_task(flush_midway()))
    start.set()
    await asyncio.gather(*tasks)

    # Holds made before the flush are gone (their seats are free again).
    # Whatever survived, holds plus the counter must add up to exactly 50.
    held = await live_held(redis, sale)
    remaining = await counter(redis, sale)
    assert held <= CAPACITY
    if remaining is not None:  # (None: nobody asked again after the flush)
        assert held + remaining == CAPACITY


async def test_the_worker_rebuilds_its_consumer_group_after_a_flush(
    client: AsyncClient,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
    redis: Redis,
    db_engine: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    worker = asyncio.create_task(
        run_consumer(redis, build_handlers(sessions, redis), build_compensations(sessions, redis))
    )

    async def wait_until_confirmed(expected: int) -> None:
        for _ in range(100):
            if await one_value(db_engine, "SELECT count(*) FROM tickets") == expected:
                return
            await asyncio.sleep(0.1)
        raise AssertionError(f"expected {expected} tickets, got fewer")

    try:
        first = await hold(client, sale, user_id=buyers[0], quantity=2)
        await confirm(client, first.json()["hold_id"], buyers[0])
        await relay_batch(sessions, redis)
        await wait_until_confirmed(2)

        await redis.flushdb()  # the stream and the consumer group vanish

        second = await hold(client, sale, user_id=buyers[1], quantity=3)
        await confirm(client, second.json()["hold_id"], buyers[1])
        await relay_batch(sessions, redis)  # published to a brand-new stream
        await wait_until_confirmed(5)  # the running worker found it anyway
    finally:
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass
