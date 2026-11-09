"""Flag an event as changed, so the live publisher sends its new availability (S7.3).

Called right after each successful inventory change (a hold made or released,
seats sold or returned, a counter rebuilt). Many changes in a burst collapse
into one flag, so subscribers get at most one update per publisher tick.
"""

from redis.asyncio import Redis

from app.redis.keys import EVENTS_CHANGED_KEY


async def mark_changed(redis: Redis, event_id: int) -> None:
    await redis.sadd(EVENTS_CHANGED_KEY, str(event_id))
