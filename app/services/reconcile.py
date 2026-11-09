"""Reconcile: recompute an event's Redis inventory counters from the truth and overwrite them.

Rehydrate (S2.8) only fills in a MISSING counter. Reconcile also fixes a
counter that exists but is wrong (Redis lost writes, a bug, a manual edit).
For each tier, under the same lock rehydrate uses:

1. GETDEL the counter. While it's missing, new holds can't take seats: they
   see "not initialised" and wait for the lock holder (us) to finish.
2. Recompute it (Postgres snapshot first, then the live holds in Redis).
3. SET the new value.
"""

from dataclasses import dataclass

from redis.asyncio import Redis
from redis.exceptions import LockError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import EventNotFound, InventoryNotReady
from app.db.models import Event, Tier
from app.redis.keys import inventory_key, rehydrate_lock_key
from app.redis.rehydrate import LOCK_SECONDS, compute_available

# How long to wait if a rehydrate is holding a tier's lock right now.
LOCK_WAIT_SECONDS = 5


@dataclass(frozen=True)
class TierReconciled:
    tier_id: int
    before: int | None  # None: the counter was missing
    after: int


async def reconcile_tier(
    session: AsyncSession, redis: Redis, event_id: int, tier_id: int
) -> TierReconciled:
    counter = inventory_key(event_id, tier_id)
    lock = redis.lock(
        rehydrate_lock_key(event_id, tier_id),
        timeout=LOCK_SECONDS,
        blocking_timeout=LOCK_WAIT_SECONDS,
    )
    if not await lock.acquire():
        raise InventoryNotReady()
    try:
        # Read and remove in one step, so no hold can slip in between the two.
        raw_before = await redis.getdel(counter)
        after = await compute_available(session, redis, event_id, tier_id)
        await redis.set(counter, after)
    finally:
        try:
            await lock.release()
        except LockError:
            pass  # it expired on its own; nothing left to release
    before = None if raw_before is None else int(raw_before)
    return TierReconciled(tier_id, before, after)


async def reconcile_event(
    session: AsyncSession, redis: Redis, event_id: int
) -> list[TierReconciled]:
    """Reconcile every tier of the event. Raises EventNotFound for an unknown event."""
    if await session.get(Event, event_id) is None:
        raise EventNotFound()
    tier_ids = (
        await session.scalars(select(Tier.id).where(Tier.event_id == event_id).order_by(Tier.id))
    ).all()
    return [await reconcile_tier(session, redis, event_id, tier_id) for tier_id in tier_ids]
