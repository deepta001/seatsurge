"""Adversarial test 4: with Redis wiped or wrong, Postgres never issues more tickets than seats.

Redis is the fast gate, but it can be flushed or out of date. These tests go
around it (orders written straight into the database, or a Redis counter
that lies) and check the last line of defence: the conditional UPDATE on
`tiers` and the unique index on ticket numbers. The reserved-seating version
(one seat, one ticket) comes with seats in S6.3.
"""

import asyncio
import random
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.job_errors import InvariantViolation
from app.redis.keys import DEAD_LETTER_STREAM_KEY, ORDERS_STREAM_KEY, inventory_key
from app.services.payments import MockPaymentProvider
from app.services.tickets import issue_tickets
from tests.outbox import run_pipeline
from tests.sales import Sale, confirm, hold, stream_messages

CAPACITY = 50  # the `sale` fixture's tier


async def pending_orders_straight_into_the_db(
    db_engine: AsyncEngine, sale: Sale, buyers: list[int], quantities: list[int]
) -> list[uuid.UUID]:
    """PENDING orders that never went through Redis, as if Redis had been wiped."""
    ids = [uuid.uuid4() for _ in quantities]
    async with db_engine.begin() as conn:
        for n, (order_id, quantity) in enumerate(zip(ids, quantities, strict=True)):
            await conn.execute(
                text(
                    "INSERT INTO orders (id, user_id, event_id, tier_id, quantity, hold_id, "
                    "idempotency_key, total_cents) VALUES (:id, :u, :e, :t, :q, :h, :k, 0)"
                ),
                {
                    "id": order_id,
                    "u": buyers[n % len(buyers)],
                    "e": sale.event_id,
                    "t": sale.tier_id,
                    "q": quantity,
                    "h": f"no-redis-{n}",
                    "k": f"key-{n}",
                },
            )
    return ids


async def issue_all_at_once(
    sessions: async_sessionmaker[AsyncSession], order_ids: list[uuid.UUID]
) -> list[Any]:
    """Run issue_tickets for every order concurrently, each in its own transaction."""
    start = asyncio.Event()

    async def one(order_id: uuid.UUID) -> Any:
        await start.wait()  # everyone begins together
        async with sessions() as session, session.begin():
            return await issue_tickets(session, order_id)

    tasks = [asyncio.create_task(one(order_id)) for order_id in order_ids]
    start.set()
    return await asyncio.gather(*tasks, return_exceptions=True)


async def query(db_engine: AsyncEngine, sql: str) -> list[Any]:
    async with db_engine.connect() as conn:
        return list((await conn.execute(text(sql))).mappings())


async def check_db_is_consistent(db_engine: AsyncEngine, sale: Sale) -> int:
    """sold == issued tickets <= capacity, numbers unique and 1..sold. Returns sold."""
    [tier] = await query(
        db_engine, f"SELECT sold, next_number FROM tiers WHERE id = {sale.tier_id}"
    )
    numbers = [
        t["ticket_number"] for t in await query(db_engine, "SELECT ticket_number FROM tickets")
    ]
    assert tier["sold"] <= CAPACITY
    assert len(numbers) == tier["sold"] == tier["next_number"]
    assert sorted(numbers) == list(range(1, tier["sold"] + 1))
    return int(tier["sold"])


async def test_sixty_single_seat_orders_on_fifty_seats_with_redis_wiped(
    client: AsyncClient,
    sale: Sale,
    buyers: list[int],
    redis: Redis,
    sessions: async_sessionmaker[AsyncSession],
    db_engine: AsyncEngine,
) -> None:
    await redis.flushdb()  # Redis knows nothing
    order_ids = await pending_orders_straight_into_the_db(db_engine, sale, buyers, [1] * 60)

    results = await issue_all_at_once(sessions, order_ids)

    issued = [r for r in results if not isinstance(r, BaseException)]
    refused = [r for r in results if isinstance(r, BaseException)]
    assert len(issued) == CAPACITY
    assert len(refused) == 10
    assert all(isinstance(r, InvariantViolation) for r in refused)  # that exact error
    assert await check_db_is_consistent(db_engine, sale) == CAPACITY
    statuses = await query(db_engine, "SELECT status, count(*) AS n FROM orders GROUP BY status")
    assert {s["status"]: s["n"] for s in statuses} == {"CONFIRMED": 50, "PENDING": 10}


async def test_mixed_size_orders_never_pass_capacity(
    client: AsyncClient,
    sale: Sale,
    buyers: list[int],
    redis: Redis,
    sessions: async_sessionmaker[AsyncSession],
    db_engine: AsyncEngine,
) -> None:
    await redis.flushdb()
    quantities = [random.randint(1, 4) for _ in range(40)]  # about 100 seats wanted
    order_ids = await pending_orders_straight_into_the_db(db_engine, sale, buyers, quantities)

    results = await issue_all_at_once(sessions, order_ids)

    refused = [r for r in results if isinstance(r, BaseException)]
    assert all(isinstance(r, InvariantViolation) for r in refused)
    sold = await check_db_is_consistent(db_engine, sale)
    issued_seats = sum(
        q
        for q, r in zip(quantities, results, strict=True)
        if r is not None and not isinstance(r, BaseException)
    )
    assert sold == issued_seats
    # Every refused order was too big for what was left when it ran.
    smallest_refused = min(
        (q for q, r in zip(quantities, results, strict=True) if isinstance(r, BaseException)),
        default=None,
    )
    if smallest_refused is not None:
        assert sold + smallest_refused > CAPACITY


async def test_a_redis_counter_that_lies_cannot_cause_an_oversell(
    client: AsyncClient,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
    redis: Redis,
    sessions: async_sessionmaker[AsyncSession],
    db_engine: AsyncEngine,
) -> None:
    # The tier is really sold out in Postgres...
    async with db_engine.begin() as conn:
        await conn.execute(
            text("UPDATE tiers SET sold = capacity, next_number = capacity WHERE id = :t"),
            {"t": sale.tier_id},
        )
    # ...but Redis wrongly says 5 seats are free, so a hold and confirm succeed.
    await redis.set(inventory_key(sale.event_id, sale.tier_id), 5)
    held = await hold(client, sale, user_id=buyers[0], quantity=2)
    assert held.status_code == 201
    assert (await confirm(client, held.json()["hold_id"], buyers[0])).status_code == 202

    assert await run_pipeline(sessions, redis) == 0  # the worker's backstop refused it

    [order] = await query(db_engine, "SELECT status FROM orders")
    assert order["status"] == "FAILED"
    assert await query(db_engine, "SELECT id FROM tickets") == []
    [tier] = await query(db_engine, f"SELECT sold FROM tiers WHERE id = {sale.tier_id}")
    assert tier["sold"] == CAPACITY
    # Dead-lettered at once (retrying can't help), with the reason recorded...
    [dead] = await stream_messages(redis, DEAD_LETTER_STREAM_KEY)
    assert dead["dead_reason"].startswith("InvariantViolation")
    assert (await redis.xpending(ORDERS_STREAM_KEY, "order-workers"))["pending"] == 0
    # ...and the hold's 2 seats went back to the (wrong) Redis counter: no leak.
    assert await redis.get(inventory_key(sale.event_id, sale.tier_id)) == "5"


async def test_the_ticket_number_index_rejects_a_second_issued_ticket(
    client: AsyncClient,
    sale: Sale,
    buyers: list[int],
    redis: Redis,
    sessions: async_sessionmaker[AsyncSession],
    db_engine: AsyncEngine,
) -> None:
    [order_id] = await pending_orders_straight_into_the_db(db_engine, sale, buyers, [1])
    await issue_all_at_once(sessions, [order_id])

    # Code that skipped the counter and reused number 1 is stopped by Postgres.
    insert = text(
        "INSERT INTO tickets (order_id, event_id, tier_id, ticket_number) VALUES (:o, :e, :t, 1)"
    )
    with pytest.raises(IntegrityError, match="uq_tickets_issued_number"):
        async with db_engine.begin() as conn:
            await conn.execute(insert, {"o": order_id, "e": sale.event_id, "t": sale.tier_id})
