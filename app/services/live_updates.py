"""What a live update says about an event right now (S7.3).

General admission: each tier's available count, read from Redis at the
moment of publishing, so it's never an intermediate or negative value. A
tier whose counter is missing is left out (never guessed, rule 4).
Reserved seating: a hint that the seat map changed; clients re-fetch the
compact map (GET /events/{id}/seats) rather than receive every seat here.
"""

from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Event, SeatingType, Tier
from app.redis.keys import inventory_key


async def availability_snapshot(
    session: AsyncSession, redis: Redis, event_id: int
) -> dict[str, Any] | None:
    """The event's current availability as a small dict, or None for an unknown event."""
    event = await session.get(Event, event_id)
    if event is None:
        return None
    if event.seating == SeatingType.RESERVED:
        return {"event_id": event_id, "seat_map_changed": True}

    tier_ids = list(
        await session.scalars(select(Tier.id).where(Tier.event_id == event_id).order_by(Tier.id))
    )
    counts = await redis.mget([inventory_key(event_id, tier_id) for tier_id in tier_ids])
    tiers = [
        {"tier_id": tier_id, "available": max(0, int(count))}
        for tier_id, count in zip(tier_ids, counts, strict=True)
        if count is not None
    ]
    return {"event_id": event_id, "tiers": tiers}
