"""The outbox relay: copies committed outbox rows onto the `stream:orders` Redis Stream.

Confirm writes "issue these tickets" into `outbox_events` in the same
transaction as the order. This task picks up PENDING rows, publishes each one
with XADD, and marks it PUBLISHED. `FOR UPDATE SKIP LOCKED` lets several
relays run at once without waiting on, or double-publishing, each other's rows.
"""

import asyncio
import json
import logging
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.outbox_models import OutboxEvent, OutboxStatus
from app.redis.keys import ORDERS_STREAM_KEY

logger = logging.getLogger(__name__)

BATCH_SIZE = 50


def stream_fields(row: OutboxEvent) -> dict[str, str]:
    """A stream entry is a flat map of strings, so the JSON payload is sent as text.

    `outbox_id` travels with the message: if a row is ever published twice
    (see `relay_batch`), both copies carry the same id, so the consumer can
    recognise the duplicate even though Redis gives each copy a new entry id.
    """
    return {
        "outbox_id": str(row.id),
        "type": row.type,
        "aggregate_id": row.aggregate_id,
        "payload": json.dumps(row.payload),
    }


async def relay_batch(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    *,
    batch_size: int = BATCH_SIZE,
) -> int:
    """Publish up to `batch_size` due PENDING rows, oldest first. Returns how many.

    Order of work: XADD each row, then commit "PUBLISHED" for the batch. If
    the process dies between the two, the rows are still PENDING and get
    published again later: a duplicate, never a loss (at-least-once). The
    consumer de-duplicates by `outbox_id` (S4.4).
    """
    async with session_factory() as session, session.begin():
        query = (
            select(OutboxEvent)
            .where(
                OutboxEvent.status == OutboxStatus.PENDING,
                OutboxEvent.next_retry_at <= func.now(),
            )
            .order_by(OutboxEvent.id)
            .limit(batch_size)
            # Lock the rows we take; another relay skips them instead of
            # waiting, and takes the next unlocked ones.
            .with_for_update(skip_locked=True)
        )
        rows = (await session.scalars(query)).all()

        published = 0
        for row in rows:
            # One bad row must never block the rows behind it. For now a
            # failed row just stays PENDING; S4.2 adds attempts and backoff.
            try:
                await redis.xadd(ORDERS_STREAM_KEY, stream_fields(row))  # type: ignore[arg-type]
            except Exception:
                logger.exception("relay: could not publish outbox row %s", row.id)
                continue
            row.status = OutboxStatus.PUBLISHED
            row.published_at = datetime.now(UTC)
            published += 1
        # Leaving the `begin()` block commits, which also releases the row locks.
    return published


async def run_relay(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    *,
    idle_seconds: float = 0.5,
) -> None:
    """Relay forever. A full batch means more may be waiting, so go again at once."""
    logger.info("relay started")
    while True:
        try:
            published = await relay_batch(session_factory, redis)
        except Exception:
            # Postgres or Redis briefly down: log it and try again next tick.
            logger.exception("relay: pass failed; retrying next tick")
            published = 0
        if published:
            logger.info("relay: published %d outbox row(s)", published)
        if published < BATCH_SIZE:
            await asyncio.sleep(idle_seconds)
