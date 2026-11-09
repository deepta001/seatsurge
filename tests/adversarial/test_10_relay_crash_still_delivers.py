"""Adversarial test 10: the relay crashes around the publish step; the order is still delivered.

Three crash points:
1. The order is committed while no relay is running at all.
2. The relay dies right after XADD, before it could mark the row PUBLISHED
   (so the message is published twice).
3. The relay's database connection dies while it holds the row locks.
In every case the order ends CONFIRMED with exactly its tickets, once.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.redis.keys import ORDERS_STREAM_KEY
from app.services.payments import MockPaymentProvider
from app.worker.relay import relay_batch
from tests.outbox import run_pipeline
from tests.sales import Sale, confirm, hold, stream_messages


class ProcessKilled(BaseException):
    """Stands in for the process dying (kill -9, power loss).

    A BaseException, not an Exception, so the relay's own `except Exception`
    can't catch it: like a real crash, nothing after this point runs.
    """


async def place_order(client: AsyncClient, sale: Sale, user_id: int, quantity: int) -> None:
    held = await hold(client, sale, user_id=user_id, quantity=quantity)
    assert held.status_code == 201
    assert (await confirm(client, held.json()["hold_id"], user_id)).status_code == 202


async def one_value(db_engine: AsyncEngine, sql: str) -> Any:
    async with db_engine.connect() as conn:
        return await conn.scalar(text(sql))


async def assert_delivered_once(db_engine: AsyncEngine, quantity: int) -> None:
    assert await one_value(db_engine, "SELECT status FROM orders") == "CONFIRMED"
    assert await one_value(db_engine, "SELECT count(*) FROM tickets") == quantity
    assert await one_value(db_engine, "SELECT status FROM outbox_events") == "PUBLISHED"
    assert await one_value(db_engine, "SELECT count(*) FROM processed_messages") == 1


async def test_an_order_committed_while_no_relay_runs_is_delivered_when_it_starts(
    client: AsyncClient,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
    redis: Redis,
    db_engine: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await place_order(client, sale, buyers[0], quantity=2)
    # The relay is down: nothing published, but the work is safe in the outbox.
    assert await stream_messages(redis, ORDERS_STREAM_KEY) == []
    assert await one_value(db_engine, "SELECT status FROM outbox_events") == "PENDING"

    assert await run_pipeline(sessions, redis) == 1  # the relay comes back

    await assert_delivered_once(db_engine, quantity=2)


async def test_a_relay_killed_after_publishing_causes_a_duplicate_that_is_harmless(
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
    real_xadd = redis.xadd

    async def xadd_then_die(*args: Any, **kwargs: Any) -> Any:
        await real_xadd(*args, **kwargs)  # the message really is published...
        raise ProcessKilled()  # ...then the process dies before its commit

    monkeypatch.setattr(redis, "xadd", xadd_then_die)
    with pytest.raises(ProcessKilled):
        await relay_batch(sessions, redis)
    monkeypatch.undo()

    # The commit never happened: the row is still PENDING, yet the message is out.
    assert await one_value(db_engine, "SELECT status FROM outbox_events") == "PENDING"
    assert len(await stream_messages(redis, ORDERS_STREAM_KEY)) == 1

    # A restarted relay publishes it AGAIN; the worker sees both copies.
    await run_pipeline(sessions, redis)

    copies = await stream_messages(redis, ORDERS_STREAM_KEY)
    assert len(copies) == 2
    assert copies[0]["outbox_id"] == copies[1]["outbox_id"]  # same message, twice
    await assert_delivered_once(db_engine, quantity=3)  # still only 3 tickets
    assert (await redis.xpending(ORDERS_STREAM_KEY, "order-workers"))["pending"] == 0


async def test_a_relay_whose_connection_dies_mid_batch_does_not_block_the_next_one(
    client: AsyncClient,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
    redis: Redis,
    db_engine: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await place_order(client, sale, buyers[0], quantity=1)

    # A relay takes the row lock, then its server connection is killed.
    async with db_engine.connect() as doomed_relay, db_engine.connect() as admin:
        await doomed_relay.begin()
        await doomed_relay.execute(
            text("SELECT id FROM outbox_events WHERE status = 'PENDING' FOR UPDATE")
        )
        backend_pid = await doomed_relay.scalar(text("SELECT pg_backend_pid()"))
        await admin.execute(text("SELECT pg_terminate_backend(:p)"), {"p": backend_pid})
        await admin.commit()
        await doomed_relay.invalidate()  # this connection is gone for good

    # Postgres released the dead connection's locks, so a new relay gets the row.
    assert await run_pipeline(sessions, redis) == 1

    await assert_delivered_once(db_engine, quantity=1)
