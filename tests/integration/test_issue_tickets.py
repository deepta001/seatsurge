"""Issuing tickets: the service on its own, and the whole hold -> confirm -> worker pipeline."""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.job_errors import PermanentError
from app.redis import confirm_scripts
from app.redis.confirm_scripts import FinishHoldScript, FinishOutcome
from app.redis.keys import (
    HOLDS_CONFIRMING_KEY,
    ORDERS_STREAM_KEY,
    hold_key,
    inventory_key,
    user_hold_key,
)
from app.services.payments import MockPaymentProvider
from app.services.tickets import issue_tickets
from tests.outbox import run_pipeline
from tests.sales import Sale, confirm, hold, stream_messages


async def query(db_engine: AsyncEngine, sql: str, **params: Any) -> list[Any]:
    async with db_engine.connect() as conn:
        return list((await conn.execute(text(sql), params)).mappings())


async def place_order(
    client: AsyncClient, sale: Sale, user_id: int, quantity: int
) -> dict[str, str]:
    """A real hold and confirm through the API. Returns the order id and hold id."""
    held = await hold(client, sale, user_id=user_id, quantity=quantity)
    assert held.status_code == 201
    hold_id = held.json()["hold_id"]
    confirmed = await confirm(client, hold_id, user_id)
    assert confirmed.status_code == 202
    return {"order_id": confirmed.json()["order_id"], "hold_id": hold_id}


async def issue_in_own_transaction(
    sessions: async_sessionmaker[AsyncSession], order_id: str
) -> list[int] | None:
    async with sessions() as session, session.begin():
        issued = await issue_tickets(session, uuid.UUID(order_id))
    return None if issued is None else issued.ticket_numbers


async def test_tickets_are_numbered_in_order_and_the_order_is_confirmed(
    client: AsyncClient,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
    sessions: async_sessionmaker[AsyncSession],
    db_engine: AsyncEngine,
) -> None:
    first = await place_order(client, sale, buyers[0], quantity=3)
    second = await place_order(client, sale, buyers[1], quantity=2)

    assert await issue_in_own_transaction(sessions, first["order_id"]) == [1, 2, 3]
    assert await issue_in_own_transaction(sessions, second["order_id"]) == [4, 5]

    [tier] = await query(
        db_engine, "SELECT sold, next_number FROM tiers WHERE id = :t", t=sale.tier_id
    )
    assert (tier["sold"], tier["next_number"]) == (5, 5)
    orders = await query(db_engine, "SELECT status FROM orders")
    assert {o["status"] for o in orders} == {"CONFIRMED"}
    tickets = await query(
        db_engine,
        "SELECT ticket_number, status FROM tickets WHERE order_id = :o ORDER BY 1",
        o=uuid.UUID(second["order_id"]),
    )
    assert [(t["ticket_number"], t["status"]) for t in tickets] == [(4, "ISSUED"), (5, "ISSUED")]


async def test_an_order_that_is_not_pending_gets_nothing(
    client: AsyncClient,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
    sessions: async_sessionmaker[AsyncSession],
    db_engine: AsyncEngine,
) -> None:
    placed = await place_order(client, sale, buyers[0], quantity=2)
    async with db_engine.begin() as conn:
        await conn.execute(text("UPDATE orders SET status = 'CANCELLED'"))

    assert await issue_in_own_transaction(sessions, placed["order_id"]) is None

    assert await query(db_engine, "SELECT id FROM tickets") == []
    [tier] = await query(db_engine, "SELECT sold FROM tiers WHERE id = :t", t=sale.tier_id)
    assert tier["sold"] == 0


async def test_an_unknown_order_is_a_permanent_error(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    with pytest.raises(PermanentError):
        await issue_in_own_transaction(sessions, str(uuid.uuid4()))


async def test_the_worker_pipeline_issues_tickets_and_consumes_the_hold(
    client: AsyncClient,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
    sessions: async_sessionmaker[AsyncSession],
    db_engine: AsyncEngine,
    redis: Redis,
) -> None:
    placed = await place_order(client, sale, buyers[0], quantity=3)

    assert await run_pipeline(sessions, redis) == 1

    [order] = await query(db_engine, "SELECT status FROM orders")
    assert order["status"] == "CONFIRMED"
    tickets = await query(db_engine, "SELECT ticket_number FROM tickets ORDER BY 1")
    assert [t["ticket_number"] for t in tickets] == [1, 2, 3]
    # Redis, after the commit: the hold is CONSUMED and no longer counts as held...
    assert await redis.hget(hold_key(placed["hold_id"]), "status") == "CONSUMED"
    assert await redis.zscore(HOLDS_CONFIRMING_KEY, placed["hold_id"]) is None
    assert await redis.get(user_hold_key(sale.event_id, buyers[0])) is None
    # ...but its seats stay sold: they are not given back to the counter.
    assert await redis.get(inventory_key(sale.event_id, sale.tier_id)) == "47"
    assert (await redis.xpending(ORDERS_STREAM_KEY, "order-workers"))["pending"] == 0
    # Confirming again returns the same order, now CONFIRMED.
    again = await confirm(client, placed["hold_id"], buyers[0])
    assert again.json() == {"order_id": placed["order_id"], "status": "CONFIRMED"}


async def test_a_crash_after_the_commit_is_finished_by_the_redelivered_duplicate(
    client: AsyncClient,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
    sessions: async_sessionmaker[AsyncSession],
    db_engine: AsyncEngine,
    redis: Redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    placed = await place_order(client, sale, buyers[0], quantity=2)
    real_call = FinishHoldScript.__call__

    async def redis_step_crashes(self: FinishHoldScript, *args: Any, **kwargs: Any) -> Any:
        raise ConnectionError("simulated crash after the database commit")

    monkeypatch.setattr(confirm_scripts.FinishHoldScript, "__call__", redis_step_crashes)
    assert await run_pipeline(sessions, redis) == 0  # not acked: the Redis step failed

    # The tickets are committed; the hold is still CONFIRMING.
    assert len(await query(db_engine, "SELECT id FROM tickets")) == 2
    assert await redis.hget(hold_key(placed["hold_id"]), "status") == "CONFIRMING"

    # The message comes again (S4.6 will redeliver it; here the stream copy is re-added).
    monkeypatch.setattr(confirm_scripts.FinishHoldScript, "__call__", real_call)
    [fields] = await stream_messages(redis, ORDERS_STREAM_KEY)
    await redis.xadd(ORDERS_STREAM_KEY, fields)  # type: ignore[arg-type]
    assert await run_pipeline(sessions, redis) == 1

    assert len(await query(db_engine, "SELECT id FROM tickets")) == 2  # still 2, not 4
    assert await redis.hget(hold_key(placed["hold_id"]), "status") == "CONSUMED"
    assert await redis.get(user_hold_key(sale.event_id, buyers[0])) is None


async def test_finishing_a_hold_twice_changes_nothing_the_second_time(
    client: AsyncClient,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
    redis: Redis,
) -> None:
    placed = await place_order(client, sale, buyers[0], quantity=2)
    # The same user also holds 3 more seats that must stay counted.
    assert (await hold(client, sale, user_id=buyers[0], quantity=3)).status_code == 201
    finish = FinishHoldScript(redis)

    first = await finish(placed["hold_id"], event_id=sale.event_id, user_id=buyers[0])
    second = await finish(placed["hold_id"], event_id=sale.event_id, user_id=buyers[0])

    assert (first, second) == (FinishOutcome.FINISHED, FinishOutcome.NOT_CONFIRMING)
    assert await redis.get(user_hold_key(sale.event_id, buyers[0])) == "3"
    # Another user's id doesn't match the hold: refused, nothing changed.
    assert await finish(placed["hold_id"], event_id=sale.event_id, user_id=buyers[1]) == (
        FinishOutcome.KEY_MISMATCH
    )
