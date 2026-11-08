"""Rebuild a missing inventory counter from the source of truth (CLAUDE.md rule 4).

A missing `inv:{event}:{tier}:avail` key means "not set up" (Redis restarted,
was flushed, or the tier is new), never "zero seats". This module recomputes
it as:

    available = capacity - sold (Postgres) - seats in active holds (Redis)
                - seats in PENDING orders (Postgres; Phase C, 0 for now)

Only ONE process rebuilds a given counter at a time (a Redis lock), and the
result is written with SET NX, so it can never overwrite a live counter.
"""

import asyncio
import logging

from redis.asyncio import Redis
from redis.exceptions import LockError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Tier
from app.redis.keys import HOLDS_EXPIRY_KEY, hold_key, inventory_key, rehydrate_lock_key

logger = logging.getLogger(__name__)

# Holds whose seats are still taken. RELEASED/EXPIRED gave theirs back, and
# CONSUMED ones are counted in `sold` (Phase C).
ACTIVE_HOLD_STATUSES = {"HELD", "CONFIRMING"}
# If the rebuilder crashes, its lock frees itself after this long.
LOCK_SECONDS = 10
# How long other requests wait for someone else's rebuild before giving up (503).
WAIT_SECONDS = 2.0
POLL_SECONDS = 0.05


async def seats_in_active_holds(redis: Redis, event_id: int, tier_id: int) -> int:
    """Sum the quantity of every live hold on this tier.

    Every live hold is listed in holds:expiry. This walks all of them, which is
    fine at this scale; a per-tier index would make it cheaper if needed.
    """
    total = 0
    async for member, _score in redis.zscan_iter(HOLDS_EXPIRY_KEY):
        status, event, tier, qty = await redis.hmget(
            hold_key(str(member)), ["status", "event", "tier", "qty"]
        )
        if status in ACTIVE_HOLD_STATUSES and event == str(event_id) and tier == str(tier_id):
            total += int(qty or 0)
    return total


async def compute_available(
    session: AsyncSession, redis: Redis, event_id: int, tier_id: int
) -> int:
    tier = await session.get(Tier, tier_id)
    if tier is None or tier.event_id != event_id:
        raise ValueError(f"tier {tier_id} does not belong to event {event_id}")
    held = await seats_in_active_holds(redis, event_id, tier_id)
    pending_orders = 0  # Phase C: + seats in PENDING orders not yet fulfilled
    # Never negative: if the sums ever disagree, under-selling is the safe side.
    return max(0, tier.capacity - tier.sold - held - pending_orders)


async def rehydrate_tier(session: AsyncSession, redis: Redis, event_id: int, tier_id: int) -> bool:
    """Make sure the tier's counter exists. True if it does now, False if we gave up."""
    counter = inventory_key(event_id, tier_id)
    lock = redis.lock(rehydrate_lock_key(event_id, tier_id), timeout=LOCK_SECONDS)

    if await lock.acquire(blocking=False):
        try:
            # Check again under the lock: someone may have just finished.
            if not await redis.exists(counter):
                available = await compute_available(session, redis, event_id, tier_id)
                # NX: never overwrite a counter that appeared in the meantime.
                await redis.set(counter, available, nx=True)
                logger.info("rehydrated %s = %d", counter, available)
        finally:
            try:
                await lock.release()
            except LockError:
                # Our lock expired before we finished; harmless, it's gone anyway.
                logger.warning("rehydrate lock for %s expired before release", counter)
        return True

    # Someone else is rebuilding it: wait (briefly) for the counter to appear.
    loop = asyncio.get_running_loop()
    deadline = loop.time() + WAIT_SECONDS
    while loop.time() < deadline:
        if await redis.exists(counter):
            return True
        await asyncio.sleep(POLL_SECONDS)
    return False
