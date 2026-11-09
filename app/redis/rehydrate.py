"""Rebuild a missing inventory counter from the source of truth (CLAUDE.md rule 4).

A missing `inv:{event}:{tier}:avail` key means "not set up" (Redis restarted,
was flushed, or the tier is new), never "zero seats". This module recomputes
it as:

    available = capacity - sold (Postgres) - seats in live holds (Redis)
                - seats in PENDING orders whose hold is gone from Redis (Postgres)

Only ONE process rebuilds a given counter at a time (a Redis lock), and the
result is written with SET NX, so it can never overwrite a live counter.
"""

import asyncio
import logging
from dataclasses import dataclass

from redis.asyncio import Redis
from redis.exceptions import LockError, ResponseError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.redis.keys import (
    HOLDS_CONFIRMING_KEY,
    HOLDS_EXPIRY_KEY,
    hold_key,
    inventory_key,
    rehydrate_lock_key,
)

logger = logging.getLogger(__name__)

# Holds whose seats are still taken. RELEASED/EXPIRED gave theirs back, and
# CONSUMED ones are counted in `sold` (Phase C).
ACTIVE_HOLD_STATUSES = {"HELD", "CONFIRMING"}
# If the rebuilder crashes, its lock frees itself after this long.
LOCK_SECONDS = 10
# How long other requests wait for someone else's rebuild before giving up (503).
WAIT_SECONDS = 2.0
POLL_SECONDS = 0.05


async def active_holds(redis: Redis, event_id: int, tier_id: int) -> dict[str, int]:
    """Every live hold on this tier, as {hold_id: quantity}.

    Live holds are listed in holds:expiry (HELD) or holds:confirming (being
    bought). This walks both, which is fine at this scale; a per-tier index
    would make it cheaper if needed.
    """
    holds: dict[str, int] = {}
    for index_key in (HOLDS_EXPIRY_KEY, HOLDS_CONFIRMING_KEY):
        async for member, _score in redis.zscan_iter(index_key):
            hold_id = str(member)
            try:
                status, event, tier, qty = await redis.hmget(
                    hold_key(hold_id), ["status", "event", "tier", "qty"]
                )
            except ResponseError:
                # Not a hash, so not a real hold (found in S3.3: one corrupt entry
                # used to block every rebuild and halt the sale). Skipping it can't
                # hide real held seats; log it so someone can look.
                logger.warning("rehydrate: skipping malformed hold record %s", hold_id)
                continue
            if status in ACTIVE_HOLD_STATUSES and event == str(event_id) and tier == str(tier_id):
                holds[hold_id] = int(qty or 0)
    return holds


@dataclass(frozen=True)
class TierSnapshot:
    """What Postgres says about one tier, all read at the same instant."""

    event_id: int
    capacity: int
    sold: int
    # hold_id -> seats, for every PENDING order on the tier.
    pending_orders: dict[str, int]


# ONE statement, so `sold` and the PENDING orders come from the same instant.
# Two separate SELECTs could straddle a worker's commit (sold +3 and the order
# turning CONFIRMED) and see neither side of it, missing those 3 seats.
TIER_SNAPSHOT = text(
    """
    SELECT t.event_id, t.capacity, t.sold,
           o.hold_id, o.quantity
      FROM tiers t
      LEFT JOIN orders o ON o.tier_id = t.id AND o.status = 'PENDING'
     WHERE t.id = :tier_id
    """
)


async def read_tier_snapshot(session: AsyncSession, tier_id: int) -> TierSnapshot | None:
    rows = (await session.execute(TIER_SNAPSHOT, {"tier_id": tier_id})).all()
    if not rows:
        return None
    first = rows[0]
    pending = {row.hold_id: row.quantity for row in rows if row.hold_id is not None}
    return TierSnapshot(first.event_id, first.capacity, first.sold, pending)


async def compute_available(
    session: AsyncSession, redis: Redis, event_id: int, tier_id: int
) -> int:
    """capacity - sold - live holds - PENDING orders whose hold is gone from Redis.

    Postgres is read FIRST (one snapshot), Redis second. In that order, a
    worker finishing an order in between can only make us count its seats
    twice (too few available: safe), never zero times (too many: oversell).
    """
    snapshot = await read_tier_snapshot(session, tier_id)
    if snapshot is None or snapshot.event_id != event_id:
        raise ValueError(f"tier {tier_id} does not belong to event {event_id}")
    holds = await active_holds(redis, event_id, tier_id)
    held = sum(holds.values())
    # A PENDING order normally still has its CONFIRMING hold in Redis, already
    # counted in `held`; only orders whose hold vanished (Redis flushed) add here.
    pending = sum(q for hold_id, q in snapshot.pending_orders.items() if hold_id not in holds)
    # Never negative: if the sums ever disagree, under-selling is the safe side.
    return max(0, snapshot.capacity - snapshot.sold - held - pending)


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
