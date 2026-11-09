"""The outbox relay publishes committed rows to `stream:orders` (real Postgres + Redis)."""

import asyncio
import json
from datetime import timedelta
from typing import Any

import pytest
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.redis.keys import ORDERS_STREAM_KEY
from app.worker.relay import RetryPolicy, delete_old_published, relay_batch
from tests.outbox import add_rows, outbox_row, published_ids, statuses
from tests.sales import stream_messages


async def test_a_pending_row_is_published_and_marked(
    sessions: async_sessionmaker[AsyncSession], db_engine: AsyncEngine, redis: Redis
) -> None:
    [row_id] = await add_rows(db_engine, 1)

    assert await relay_batch(sessions, redis) == 1

    assert await stream_messages(redis, ORDERS_STREAM_KEY) == [
        {
            "outbox_id": str(row_id),
            "type": "order.placed",
            "aggregate_id": "order-0",
            "payload": json.dumps({"n": 0}),
        }
    ]
    async with db_engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT status, published_at FROM outbox_events WHERE id = :i"), {"i": row_id}
            )
        ).one()
    assert row.status == "PUBLISHED"
    assert row.published_at is not None
    # Running again finds nothing: a published row is never sent twice by the relay.
    assert await relay_batch(sessions, redis) == 0
    assert await redis.xlen(ORDERS_STREAM_KEY) == 1


async def test_rows_not_yet_due_or_not_pending_are_left_alone(
    sessions: async_sessionmaker[AsyncSession], db_engine: AsyncEngine, redis: Redis
) -> None:
    later = await add_rows(db_engine, 1, due_in_seconds=3600)
    dead = await add_rows(db_engine, 1, status="DEAD")

    assert await relay_batch(sessions, redis) == 0

    assert await redis.xlen(ORDERS_STREAM_KEY) == 0
    found = await statuses(db_engine)
    assert found[later[0]] == "PENDING"
    assert found[dead[0]] == "DEAD"


async def test_rows_go_out_oldest_first_in_batches(
    sessions: async_sessionmaker[AsyncSession], db_engine: AsyncEngine, redis: Redis
) -> None:
    ids = await add_rows(db_engine, 5)

    assert [await relay_batch(sessions, redis, batch_size=2) for _ in range(4)] == [2, 2, 1, 0]

    assert await published_ids(redis) == ids


async def test_a_locked_row_is_skipped_not_waited_for(
    sessions: async_sessionmaker[AsyncSession], db_engine: AsyncEngine, redis: Redis
) -> None:
    first, *rest = await add_rows(db_engine, 3)

    # Another relay is busy with the oldest row and hasn't committed yet.
    async with db_engine.connect() as other_relay:
        await other_relay.begin()
        await other_relay.execute(
            text("SELECT id FROM outbox_events WHERE id = :i FOR UPDATE"), {"i": first}
        )
        # Without SKIP LOCKED this would block until the other relay finished.
        published = await asyncio.wait_for(relay_batch(sessions, redis), timeout=5)
        await other_relay.rollback()

    assert published == 2
    assert await published_ids(redis) == rest
    assert (await statuses(db_engine))[first] == "PENDING"


async def test_concurrent_relays_publish_every_row_exactly_once(
    sessions: async_sessionmaker[AsyncSession], db_engine: AsyncEngine, redis: Redis
) -> None:
    ids = await add_rows(db_engine, 200)
    start = asyncio.Event()

    async def one_relay() -> int:
        await start.wait()  # all relays begin together
        total = 0
        while published := await relay_batch(sessions, redis, batch_size=10):
            total += published
        return total

    tasks = [asyncio.create_task(one_relay()) for _ in range(4)]
    start.set()
    totals = await asyncio.gather(*tasks)

    assert sum(totals) == 200
    assert sorted(await published_ids(redis)) == ids  # each row once, none missing
    assert set((await statuses(db_engine)).values()) == {"PUBLISHED"}


async def test_one_failing_row_does_not_block_the_others(
    sessions: async_sessionmaker[AsyncSession],
    db_engine: AsyncEngine,
    redis: Redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, poison, last = await add_rows(db_engine, 3)
    real_xadd = redis.xadd

    async def xadd_failing_for_poison(name: str, fields: dict[str, str], **kwargs: Any) -> Any:
        if fields["outbox_id"] == str(poison):
            raise ResponseError("simulated failure for one row")
        return await real_xadd(name, fields, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(redis, "xadd", xadd_failing_for_poison)

    assert await relay_batch(sessions, redis) == 2

    assert await published_ids(redis) == [first, last]
    found = await statuses(db_engine)
    # Still PENDING: it will be retried later (see test 8 for the retry rules).
    assert found[poison] == "PENDING"
    assert found[first] == found[last] == "PUBLISHED"


async def test_a_failed_row_waits_for_its_backoff_before_the_next_try(
    sessions: async_sessionmaker[AsyncSession],
    db_engine: AsyncEngine,
    redis: Redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    [row_id] = await add_rows(db_engine, 1)

    async def always_rejected(*args: Any, **kwargs: Any) -> Any:
        raise ResponseError("simulated rejection")

    monkeypatch.setattr(redis, "xadd", always_rejected)
    await relay_batch(sessions, redis, policy=RetryPolicy(base_delay_seconds=60))
    await relay_batch(sessions, redis, policy=RetryPolicy(base_delay_seconds=60))

    row = await outbox_row(db_engine, row_id)
    # Tried once: the second pass found it not yet due (retry in about 60 s).
    assert (row.status, row.attempts, row.due) == ("PENDING", 1, False)


async def test_redis_being_down_costs_no_attempts(
    sessions: async_sessionmaker[AsyncSession],
    db_engine: AsyncEngine,
    redis: Redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = await add_rows(db_engine, 3)

    async def redis_unreachable(*args: Any, **kwargs: Any) -> Any:
        raise RedisConnectionError("simulated: Redis is down")

    monkeypatch.setattr(redis, "xadd", redis_unreachable)
    for _ in range(10):  # a long outage must not push rows towards DEAD
        assert await relay_batch(sessions, redis, policy=RetryPolicy(max_attempts=2)) == 0

    for row_id in ids:
        row = await outbox_row(db_engine, row_id)
        assert (row.status, row.attempts, row.due) == ("PENDING", 0, True)
    monkeypatch.undo()  # Redis is back: everything goes out
    assert await relay_batch(sessions, redis) == 3


def test_backoff_doubles_each_time_up_to_the_cap() -> None:
    policy = RetryPolicy(base_delay_seconds=1, max_delay_seconds=30)
    assert [policy.delay_after(n) for n in range(1, 8)] == [1, 2, 4, 8, 16, 30, 30]


async def test_old_published_rows_are_deleted_and_nothing_else(
    sessions: async_sessionmaker[AsyncSession], db_engine: AsyncEngine
) -> None:
    old_published, recent_published = await add_rows(db_engine, 2, status="PUBLISHED")
    [pending] = await add_rows(db_engine, 1)
    [dead] = await add_rows(db_engine, 1, status="DEAD")
    async with db_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE outbox_events SET published_at = now() - CASE id "
                "WHEN :old THEN interval '2 days' ELSE interval '1 hour' END "
                "WHERE status <> 'PENDING'"
            ),
            {"old": old_published},
        )

    deleted = await delete_old_published(sessions, older_than=timedelta(days=1))

    assert deleted == 1
    assert set(await statuses(db_engine)) == {recent_published, pending, dead}
