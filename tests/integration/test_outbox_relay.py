"""The outbox relay publishes committed rows to `stream:orders` (real Postgres + Redis)."""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.session import create_session_factory
from app.redis.keys import ORDERS_STREAM_KEY
from app.worker.relay import relay_batch
from tests.sales import stream_messages

INSERT_ROW = text(
    "INSERT INTO outbox_events (type, aggregate_id, payload, status, next_retry_at) "
    "VALUES ('order.placed', :a, CAST(:p AS jsonb), :s, now() + make_interval(secs => :d)) "
    "RETURNING id"
)


@pytest.fixture
async def sessions(db_engine: AsyncEngine) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    yield create_session_factory(db_engine)
    async with db_engine.begin() as conn:
        await conn.execute(text("TRUNCATE outbox_events RESTART IDENTITY"))


async def add_rows(
    engine: AsyncEngine, count: int, *, status: str = "PENDING", due_in_seconds: int = 0
) -> list[int]:
    ids = []
    async with engine.begin() as conn:
        for n in range(count):
            new_id = await conn.scalar(
                INSERT_ROW,
                {"a": f"order-{n}", "p": json.dumps({"n": n}), "s": status, "d": due_in_seconds},
            )
            ids.append(int(new_id))
    return ids


async def statuses(engine: AsyncEngine) -> dict[int, str]:
    async with engine.connect() as conn:
        rows = await conn.execute(text("SELECT id, status FROM outbox_events"))
        return {row.id: row.status for row in rows}


async def published_ids(redis: Redis) -> list[int]:
    return [int(m["outbox_id"]) for m in await stream_messages(redis, ORDERS_STREAM_KEY)]


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
            raise ConnectionError("simulated Redis failure for one row")
        return await real_xadd(name, fields, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(redis, "xadd", xadd_failing_for_poison)

    assert await relay_batch(sessions, redis) == 2

    assert await published_ids(redis) == [first, last]
    found = await statuses(db_engine)
    # Still PENDING, so it will be tried again (attempts and backoff come in S4.2).
    assert found[poison] == "PENDING"
    assert found[first] == found[last] == "PUBLISHED"
