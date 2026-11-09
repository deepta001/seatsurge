"""Adversarial test 13: cancel then re-buy works, and ticket numbers are never reused.

Cancel commits everything in Postgres at once (order + tickets CANCELLED,
`sold` down, an outbox row); the worker gives the seats back to Redis
afterwards, exactly once.
"""

import asyncio
import uuid
from typing import Any

import pytest
from httpx import AsyncClient, Response
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.order_models import OrderStatus
from app.redis.keys import DEAD_LETTER_STREAM_KEY, ORDERS_STREAM_KEY, inventory_key
from app.services.cancellations import cancel_order
from app.services.payments import MockPaymentProvider
from tests.outbox import run_pipeline
from tests.sales import Sale, bearer, confirm, hold, stream_messages


async def buy(
    client: AsyncClient,
    sale: Sale,
    sessions: async_sessionmaker[AsyncSession],
    redis: Redis,
    user_id: int,
    quantity: int,
) -> str:
    """Hold, confirm and let the worker issue the tickets. Returns the order id."""
    held = await hold(client, sale, user_id=user_id, quantity=quantity)
    assert held.status_code == 201
    confirmed = await confirm(client, held.json()["hold_id"], user_id)
    await run_pipeline(sessions, redis)
    return str(confirmed.json()["order_id"])


async def cancel(client: AsyncClient, order_id: str, user_id: int) -> Response:
    return await client.post(f"/orders/{order_id}/cancel", headers=bearer(user_id))


async def rows(db_engine: AsyncEngine, sql: str) -> list[Any]:
    async with db_engine.connect() as conn:
        return list((await conn.execute(text(sql))).mappings())


async def counter(redis: Redis, sale: Sale) -> str | None:
    value = await redis.get(inventory_key(sale.event_id, sale.tier_id))
    return None if value is None else str(value)


async def test_cancel_then_rebuy_gives_new_numbers_and_returns_the_seats(
    client: AsyncClient,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
    redis: Redis,
    db_engine: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    first = await buy(client, sale, sessions, redis, buyers[0], quantity=3)
    assert await counter(redis, sale) == "47"

    response = await cancel(client, first, buyers[0])

    assert response.status_code == 200
    assert response.json() == {"order_id": first, "status": "CANCELLED"}
    # Postgres changed at once, in one transaction...
    [order] = await rows(db_engine, f"SELECT status FROM orders WHERE id = '{first}'")
    assert order["status"] == "CANCELLED"
    tickets = await rows(db_engine, "SELECT ticket_number, status FROM tickets ORDER BY 1")
    assert [(t["ticket_number"], t["status"]) for t in tickets] == [
        (1, "CANCELLED"),
        (2, "CANCELLED"),
        (3, "CANCELLED"),
    ]
    [tier] = await rows(db_engine, f"SELECT sold, next_number FROM tiers WHERE id = {sale.tier_id}")
    assert (tier["sold"], tier["next_number"]) == (0, 3)  # numbers are never handed back
    # ...but Redis only after the worker reads the outbox (rule 6).
    assert await counter(redis, sale) == "47"
    await run_pipeline(sessions, redis)
    assert await counter(redis, sale) == "50"

    # Someone else buys: new ticket numbers 4-6, never 1-3 again.
    second = await buy(client, sale, sessions, redis, buyers[1], quantity=3)
    issued = await rows(
        db_engine, f"SELECT ticket_number FROM tickets WHERE order_id = '{second}' ORDER BY 1"
    )
    assert [t["ticket_number"] for t in issued] == [4, 5, 6]
    assert await stream_messages(redis, DEAD_LETTER_STREAM_KEY) == []


async def test_cancelling_twice_or_at_once_takes_the_seats_back_only_once(
    client: AsyncClient,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
    redis: Redis,
    db_engine: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    order_id = await buy(client, sale, sessions, redis, buyers[0], quantity=2)

    responses = await asyncio.gather(*(cancel(client, order_id, buyers[0]) for _ in range(10)))

    assert {r.status_code for r in responses} == {200}
    [tier] = await rows(db_engine, f"SELECT sold FROM tiers WHERE id = {sale.tier_id}")
    assert tier["sold"] == 0  # 2 - 2 once, never negative
    cancels = await rows(db_engine, "SELECT id FROM outbox_events WHERE type = 'order.cancelled'")
    assert len(cancels) == 1
    await run_pipeline(sessions, redis)
    assert await counter(redis, sale) == "50"


async def test_a_duplicate_cancel_message_returns_the_seats_once(
    client: AsyncClient,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
    redis: Redis,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    order_id = await buy(client, sale, sessions, redis, buyers[0], quantity=4)
    assert (await cancel(client, order_id, buyers[0])).status_code == 200
    await run_pipeline(sessions, redis)
    assert await counter(redis, sale) == "50"

    # The relay publishes the cancel again (crashed before marking it).
    cancel_copy = [
        m for m in await stream_messages(redis, ORDERS_STREAM_KEY) if m["type"] == "order.cancelled"
    ]
    await redis.xadd(ORDERS_STREAM_KEY, cancel_copy[0])  # type: ignore[arg-type]
    await run_pipeline(sessions, redis)

    assert await counter(redis, sale) == "50"  # not 54


async def test_a_missing_counter_is_not_created_by_a_cancel(
    client: AsyncClient,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
    redis: Redis,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    order_id = await buy(client, sale, sessions, redis, buyers[0], quantity=3)
    await redis.delete(inventory_key(sale.event_id, sale.tier_id))
    assert (await cancel(client, order_id, buyers[0])).status_code == 200
    await run_pipeline(sessions, redis)

    assert await counter(redis, sale) is None  # rule 4: a missing counter is never guessed
    # The next hold rebuilds it from Postgres, where the 3 seats are already free.
    assert (await hold(client, sale, user_id=buyers[1], quantity=1)).status_code == 201
    assert await counter(redis, sale) == "49"


async def test_only_the_owner_can_cancel_and_only_a_confirmed_order(
    client: AsyncClient,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
    redis: Redis,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    order_id = await buy(client, sale, sessions, redis, buyers[0], quantity=1)

    # Someone else's order and a made-up one look the same: 404.
    assert (await cancel(client, order_id, buyers[1])).status_code == 404
    assert (await cancel(client, str(uuid.uuid4()), buyers[0])).status_code == 404

    # A PENDING order (tickets not issued yet) can't be cancelled.
    held = await hold(client, sale, user_id=buyers[2], quantity=1)
    pending = (await confirm(client, held.json()["hold_id"], buyers[2])).json()["order_id"]
    response = await cancel(client, pending, buyers[2])
    assert response.status_code == 409
    assert response.json()["error"] == "order_not_cancellable"


async def test_a_cancelled_order_no_longer_counts_towards_the_purchase_cap(
    client: AsyncClient,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
    redis: Redis,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    order_id = await buy(client, sale, sessions, redis, buyers[0], quantity=8)
    assert (await cancel(client, order_id, buyers[0])).status_code == 200
    await run_pipeline(sessions, redis)

    # 8 cancelled + 8 new would be 16 > 10, but cancelled tickets don't count.
    await buy(client, sale, sessions, redis, buyers[0], quantity=8)


async def test_two_cancels_that_both_read_the_order_cannot_both_return_the_seats(
    client: AsyncClient,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
    redis: Redis,
    db_engine: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forces the dangerous timing every time, instead of hoping requests overlap.

    Cancel A pauses right after reading the order until cancel B has read it
    too (or 1 s passes). With the row lock, B can't read until A commits, so
    B sees CANCELLED. Without it, both would see CONFIRMED and both would
    take the seats back.
    """
    order_id = uuid.UUID(await buy(client, sale, sessions, redis, buyers[0], quantity=2))
    b_has_read = asyncio.Event()

    async with sessions() as session_a, sessions() as session_b:
        real_a_execute, real_b_scalar = session_a.execute, session_b.scalar

        async def a_pauses_after_reading(*args: Any, **kwargs: Any) -> Any:
            try:
                await asyncio.wait_for(b_has_read.wait(), timeout=1)
            except TimeoutError:
                pass  # B is waiting on A's row lock: exactly what should happen
            return await real_a_execute(*args, **kwargs)

        async def b_reads(*args: Any, **kwargs: Any) -> Any:
            result = await real_b_scalar(*args, **kwargs)
            b_has_read.set()
            return result

        monkeypatch.setattr(session_a, "execute", a_pauses_after_reading)
        monkeypatch.setattr(session_b, "scalar", b_reads)
        results = await asyncio.gather(
            cancel_order(session_a, user_id=buyers[0], order_id=order_id),
            cancel_order(session_b, user_id=buyers[0], order_id=order_id),
            return_exceptions=True,
        )

    assert list(results) == [OrderStatus.CANCELLED, OrderStatus.CANCELLED]
    [tier] = await rows(db_engine, f"SELECT sold FROM tiers WHERE id = {sale.tier_id}")
    assert tier["sold"] == 0
    cancels = await rows(db_engine, "SELECT id FROM outbox_events WHERE type = 'order.cancelled'")
    assert len(cancels) == 1
