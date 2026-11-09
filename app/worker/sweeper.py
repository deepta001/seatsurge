"""The hold sweeper: finds holds whose time is up and gives their seats back.

Every hold has an expiry time in the `holds:expiry` sorted set (score =
expires_at in ms), so "which holds have expired?" is one cheap range query.
Releasing is idempotent, so several sweepers, or a sweeper racing a user's
own cancel, can never return the same seats twice.
"""

import asyncio
import logging
import time

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from app.core.metrics import HOLD_EXPIRIES
from app.redis.keys import HOLDS_EXPIRY_KEY
from app.redis.scripts import HoldStatus, ReleaseHoldScript, ReleaseOutcome

logger = logging.getLogger(__name__)


def now_ms() -> int:
    return int(time.time() * 1000)


async def sweep_expired_holds(redis: Redis, *, now: int, batch_size: int = 100) -> int:
    """Release up to `batch_size` holds that expired at or before `now` (ms). Returns how many."""
    expired_ids = await redis.zrangebyscore(HOLDS_EXPIRY_KEY, "-inf", now, start=0, num=batch_size)
    release = ReleaseHoldScript(redis)
    released = 0
    for raw_id in expired_ids:
        hold_id = str(raw_id)  # text already (decode_responses); str() is for mypy
        try:
            outcome = await release(
                hold_id, new_status=HoldStatus.EXPIRED, owner_id=None, only_if_expired_at_ms=now
            )
        except ResponseError:
            # Not a real hold (e.g. not a hash). Left in place it would fail on
            # every pass and block every hold behind it, so drop it from the index.
            logger.error("sweeper: malformed hold %s removed from %s", hold_id, HOLDS_EXPIRY_KEY)
            await redis.zrem(HOLDS_EXPIRY_KEY, hold_id)
            continue
        if outcome == ReleaseOutcome.RELEASED:
            released += 1
            HOLD_EXPIRIES.inc()
        elif outcome == ReleaseOutcome.KEY_MISMATCH:
            # Should never happen; log it loudly and carry on with the rest.
            logger.error("sweeper: hold %s record does not match its keys", hold_id)
    return released


async def run_sweeper(redis: Redis, *, interval_seconds: float = 1.0) -> None:
    """Sweep forever. One failed pass (say, Redis briefly down) never stops the loop."""
    logger.info("sweeper started (every %.1fs)", interval_seconds)
    while True:
        try:
            released = await sweep_expired_holds(redis, now=now_ms())
            if released:
                logger.info("sweeper: released %d expired hold(s)", released)
        except Exception:
            logger.exception("sweeper: pass failed; retrying next tick")
        await asyncio.sleep(interval_seconds)
