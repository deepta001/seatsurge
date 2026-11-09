"""Reconcile: recompute an event's Redis inventory counters from the truth and overwrite them.

Rehydrate (S2.8) only fills in a MISSING counter. Reconcile also fixes a
counter that exists but is wrong (Redis lost writes, a bug, a manual edit).
For each tier, under the same lock rehydrate uses:

1. GETDEL the counter. While it's missing, new holds can't take seats: they
   see "not initialised" and wait for the lock holder (us) to finish.
2. Recompute it (Postgres snapshot first, then the live holds in Redis).
3. SET the new value.

It also re-queues the outbox rows of the event's still-PENDING orders, so an
order whose stream message was lost (Redis flushed) is published again. A
duplicate is harmless: the worker skips it (run_once), and only ever issues
tickets for a PENDING order.
"""

from dataclasses import dataclass

from redis.asyncio import Redis
from redis.exceptions import LockError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import EventNotFound, InventoryNotReady
from app.db.models import Event, SeatingType, Tier
from app.redis.keys import inventory_key, rehydrate_lock_key
from app.redis.live import mark_changed
from app.redis.rehydrate import LOCK_SECONDS, compute_available
from app.redis.seat_scripts import rebuild_sold_set

# How long to wait if a rehydrate is holding a tier's lock right now.
LOCK_WAIT_SECONDS = 5


# PUBLISHED -> PENDING again, for orders that still have no tickets. Rows that
# are PENDING already (not yet sent) or DEAD (given up on) are left alone.
REQUEUE_PENDING_ORDERS = text(
    """
    UPDATE outbox_events
       SET status = 'PENDING', next_retry_at = now(), published_at = NULL
     WHERE type = 'order.placed'
       AND status = 'PUBLISHED'
       AND aggregate_id IN (
           SELECT id::text FROM orders WHERE event_id = :event_id AND status = 'PENDING'
       )
    RETURNING id
    """
)


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
        await mark_changed(redis, event_id)
    finally:
        try:
            await lock.release()
        except LockError:
            pass  # it expired on its own; nothing left to release
    before = None if raw_before is None else int(raw_before)
    return TierReconciled(tier_id, before, after)


@dataclass(frozen=True)
class EventReconciled:
    tiers: list[TierReconciled]
    requeued_orders: int  # PENDING orders whose message was sent again


async def reconcile_event(session: AsyncSession, redis: Redis, event_id: int) -> EventReconciled:
    """Reconcile every tier, then re-queue stuck orders. EventNotFound for an unknown event."""
    event = await session.get(Event, event_id)
    if event is None:
        raise EventNotFound()
    if event.seating == SeatingType.RESERVED:
        # No counters: the seat keys and the sold set are the inventory. Rebuild
        # the sold set from Postgres (sold + PENDING orders' seats), replacing it.
        if not await rebuild_sold_set(session, redis, event_id, force=True):
            raise InventoryNotReady()
        requeued = (await session.scalars(REQUEUE_PENDING_ORDERS, {"event_id": event_id})).all()
        await session.commit()
        return EventReconciled([], len(requeued))
    tier_ids = (
        await session.scalars(select(Tier.id).where(Tier.event_id == event_id).order_by(Tier.id))
    ).all()
    tiers = [await reconcile_tier(session, redis, event_id, tier_id) for tier_id in tier_ids]
    requeued = (await session.scalars(REQUEUE_PENDING_ORDERS, {"event_id": event_id})).all()
    await session.commit()
    return EventReconciled(tiers, len(requeued))
