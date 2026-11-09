"""Backlog gauges: how much work is waiting, refreshed every few seconds (S8.2).

These numbers live in Postgres and Redis, not in this process, so a loop
reads them and sets the gauges; a Prometheus scrape then reads the gauges
instantly. A growing outbox or stream backlog is the first sign that the
relay or the consumer is stuck, long before customers notice.
"""

import asyncio
import logging
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.metrics import (
    DEAD_LETTER_STREAM_LENGTH,
    OUTBOX_DEAD,
    OUTBOX_OLDEST_PENDING_AGE,
    OUTBOX_PENDING,
    STREAM_PENDING,
)
from app.redis.keys import DEAD_LETTER_STREAM_KEY, ORDERS_STREAM_KEY
from app.worker.consumer import ORDERS_GROUP

logger = logging.getLogger(__name__)

REFRESH_SECONDS = 5.0

# One statement: counts and the oldest age come from the same snapshot.
# Age uses the database clock, like the relay's retry times.
OUTBOX_BACKLOG = text(
    """
    SELECT count(*) FILTER (WHERE status = 'PENDING') AS pending,
           count(*) FILTER (WHERE status = 'DEAD') AS dead,
           COALESCE(EXTRACT(EPOCH FROM now() - min(created_at)
                    FILTER (WHERE status = 'PENDING')), 0) AS oldest_age
      FROM outbox_events
     WHERE status IN ('PENDING', 'DEAD')
    """
)


async def refresh_outbox_gauges(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        row = (await session.execute(OUTBOX_BACKLOG)).one()
    OUTBOX_PENDING.set(row.pending)
    OUTBOX_DEAD.set(row.dead)
    OUTBOX_OLDEST_PENDING_AGE.set(float(row.oldest_age))


async def stream_pending_count(redis: Redis) -> int:
    """Messages handed to a worker but not acked yet. 0 if the stream doesn't exist yet."""
    if not await redis.exists(ORDERS_STREAM_KEY):
        return 0
    summary: Any = await redis.xpending(ORDERS_STREAM_KEY, ORDERS_GROUP)
    return int(summary["pending"])


async def refresh_stream_gauges(redis: Redis) -> None:
    STREAM_PENDING.set(await stream_pending_count(redis))
    DEAD_LETTER_STREAM_LENGTH.set(await redis.xlen(DEAD_LETTER_STREAM_KEY))


async def run_backlog_gauges(
    session_factory: async_sessionmaker[AsyncSession], redis: Redis
) -> None:
    """Refresh forever. A failed pass leaves the last values and tries again next time."""
    logger.info("backlog gauges started (every %.0fs)", REFRESH_SECONDS)
    while True:
        try:
            await refresh_outbox_gauges(session_factory)
            await refresh_stream_gauges(redis)
        except Exception:
            logger.exception("backlog gauges: refresh failed; retrying next tick")
        await asyncio.sleep(REFRESH_SECONDS)
