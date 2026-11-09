"""Shared helpers for the order pipeline: outbox rows, and running relay + consumer once."""

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.session import create_session_factory
from app.redis.keys import ORDERS_STREAM_KEY
from app.worker.consumer import consume_batch, ensure_group
from app.worker.handlers import build_compensations, build_handlers
from app.worker.relay import relay_batch
from tests.sales import stream_messages

INSERT_ROW = text(
    "INSERT INTO outbox_events (type, aggregate_id, payload, status, next_retry_at) "
    "VALUES (:t, :a, CAST(:p AS jsonb), :s, now() + make_interval(secs => :d)) "
    "RETURNING id"
)


@pytest.fixture
async def sessions(db_engine: AsyncEngine) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A session factory on the test database; the outbox table is emptied afterwards."""
    yield create_session_factory(db_engine)
    async with db_engine.begin() as conn:
        await conn.execute(text("TRUNCATE outbox_events, processed_messages RESTART IDENTITY"))


async def add_rows(
    engine: AsyncEngine,
    count: int,
    *,
    status: str = "PENDING",
    due_in_seconds: int = 0,
    event_type: str = "order.placed",
) -> list[int]:
    """Insert `count` outbox rows; returns their ids in order."""
    ids = []
    async with engine.begin() as conn:
        for n in range(count):
            new_id = await conn.scalar(
                INSERT_ROW,
                {
                    "t": event_type,
                    "a": f"order-{n}",
                    "p": json.dumps({"n": n}),
                    "s": status,
                    "d": due_in_seconds,
                },
            )
            ids.append(int(new_id))
    return ids


async def outbox_row(engine: AsyncEngine, row_id: int) -> Any:
    """One outbox row, plus whether it is due now."""
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT *, next_retry_at <= now() AS due FROM outbox_events WHERE id = :i"),
            {"i": row_id},
        )
        return result.one()


async def statuses(engine: AsyncEngine) -> dict[int, str]:
    async with engine.connect() as conn:
        rows = await conn.execute(text("SELECT id, status FROM outbox_events"))
        return {row.id: row.status for row in rows}


async def published_ids(redis: Redis) -> list[int]:
    return [int(m["outbox_id"]) for m in await stream_messages(redis, ORDERS_STREAM_KEY)]


async def run_pipeline(sessions: async_sessionmaker[AsyncSession], redis: Redis) -> int:
    """One relay pass, then one consumer pass with the real handlers. Returns how many were acked.

    What the worker process does in its loops, run once, so tests stay
    deterministic.
    """
    await relay_batch(sessions, redis)
    await ensure_group(redis)
    handlers = build_handlers(sessions, redis)
    compensations = build_compensations(sessions, redis)
    return await consume_batch(
        redis, handlers, compensations, consumer="test-worker", count=100, block_ms=None
    )
