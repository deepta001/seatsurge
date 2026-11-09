"""Retrying stuck messages: ones a worker was given but never acknowledged.

A message stays in the group's pending list (PEL) when its handler failed
or its worker crashed. This pass looks at how long each one has waited
since its last delivery and how often it has been delivered. It takes over
(XCLAIM) the ones whose backoff has passed and handles them again, or
dead-letters them once they've had their last chance.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis

from app.redis.keys import ORDERS_STREAM_KEY
from app.worker.consumer import ORDERS_GROUP, handle_entry
from app.worker.dead_letters import Compensation, dead_letter
from app.worker.messages import Handler

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RedeliveryPolicy:
    """Retry after 1 s, 2 s, 4 s, 8 s; dead-letter after 5 failed deliveries."""

    max_deliveries: int = 5
    base_delay_ms: int = 1000
    max_delay_ms: int = 60_000

    def delay_ms(self, deliveries: int) -> int:
        """How long a message delivered `deliveries` times waits before the next try."""
        return int(min(self.base_delay_ms * 2 ** max(deliveries - 1, 0), self.max_delay_ms))


DEFAULT_POLICY = RedeliveryPolicy()


async def retry_stuck(
    redis: Redis,
    handlers: Mapping[str, Handler],
    compensations: Mapping[str, Compensation],
    *,
    consumer: str,
    policy: RedeliveryPolicy = DEFAULT_POLICY,
    count: int = 50,
    stream: str = ORDERS_STREAM_KEY,
    group: str = ORDERS_GROUP,
) -> int:
    """One pass over the pending list. Returns how many retried messages succeeded."""
    stuck: list[dict[str, Any]] = await redis.xpending_range(
        stream, group, min="-", max="+", count=count, idle=policy.base_delay_ms
    )
    handled = 0
    for info in stuck:
        entry_id = str(info["message_id"])
        deliveries = int(info["times_delivered"])
        wait_ms = policy.delay_ms(deliveries)
        if int(info["time_since_delivered"]) < wait_ms:
            continue  # its backoff hasn't passed yet

        # XCLAIM with min_idle_time: if another worker claimed it a moment ago,
        # its idle time was reset and Redis gives it to nobody else. This also
        # rescues messages held by a worker that crashed.
        claimed: Any = await redis.xclaim(
            stream, group, consumer, min_idle_time=wait_ms, message_ids=[entry_id]
        )
        if not claimed or claimed[0][1] is None:
            continue  # someone else got it, or the entry itself is gone
        fields = {str(k): str(v) for k, v in claimed[0][1].items()}
        deliveries += 1  # XCLAIM counted this delivery

        if deliveries > policy.max_deliveries:
            try:
                await dead_letter(
                    redis,
                    compensations,
                    entry_id=entry_id,
                    fields=fields,
                    reason=f"gave up after {deliveries - 1} failed deliveries",
                    deliveries=deliveries - 1,
                    stream=stream,
                    group=group,
                )
            except Exception:
                logger.exception("consumer: could not dead-letter %s; will try again", entry_id)
            continue

        logger.info("consumer: retrying %s (delivery %d)", entry_id, deliveries)
        if await handle_entry(
            redis,
            handlers,
            compensations,
            entry_id=entry_id,
            fields=fields,
            deliveries=deliveries,
            stream=stream,
            group=group,
        ):
            handled += 1
    return handled
