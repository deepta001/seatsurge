"""The live publisher: turns "this event changed" flags into one update per event per tick.

Every 0.2 s it takes the changed events (SPOP from `events:changed`), reads
each one's current availability, and PUBLISHes it on `chan:event:{id}`. A
burst of 500 holds in 0.2 s becomes ONE message: at most 5 per second per
event (CLAUDE.md section 7.7), however busy the sale.
"""

import asyncio
import json
import logging

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.redis.keys import EVENTS_CHANGED_KEY, live_channel
from app.services.live_updates import availability_snapshot

logger = logging.getLogger(__name__)

TICK_SECONDS = 0.2  # 5 ticks per second: the most updates any event gets
BATCH = 500


async def publish_changes(session_factory: async_sessionmaker[AsyncSession], redis: Redis) -> int:
    """Publish one fresh snapshot per changed event. Returns how many were sent."""
    raw_ids = await redis.spop(EVENTS_CHANGED_KEY, BATCH)
    sent = 0
    async with session_factory() as session:
        for raw_id in raw_ids or []:
            event_id = int(raw_id)
            snapshot = await availability_snapshot(session, redis, event_id)
            if snapshot is None:
                continue  # the event was deleted; nothing to announce
            await redis.publish(live_channel(event_id), json.dumps(snapshot))
            sent += 1
    return sent


async def run_live_publisher(
    session_factory: async_sessionmaker[AsyncSession], redis: Redis
) -> None:
    """Publish forever. A failed tick (Redis or Postgres blip) is logged and skipped."""
    logger.info("live publisher started (every %.1fs)", TICK_SECONDS)
    while True:
        try:
            await publish_changes(session_factory, redis)
        except Exception:
            logger.exception("live publisher: tick failed; trying again next tick")
        await asyncio.sleep(TICK_SECONDS)
