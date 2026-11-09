"""The consumer's forever-loop: read new messages, then retry stuck ones, again and again."""

import asyncio
import logging
from collections.abc import Mapping

from redis.asyncio import Redis

from app.worker.consumer import consume_batch, consumer_name, ensure_group
from app.worker.dead_letters import Compensation
from app.worker.messages import Handler
from app.worker.retries import retry_stuck

logger = logging.getLogger(__name__)


async def run_consumer(
    redis: Redis, handlers: Mapping[str, Handler], compensations: Mapping[str, Compensation]
) -> None:
    """Consume forever. A failed pass (Redis briefly down) is logged and retried."""
    name = consumer_name()
    logger.info("consumer %s started", name)
    group_ready = False
    while True:
        try:
            if not group_ready:
                await ensure_group(redis)
                group_ready = True
            # Waits up to 1 s inside Redis for new messages, so this loop is
            # never a busy spin; then gives stuck messages another chance.
            handled = await consume_batch(redis, handlers, compensations, consumer=name)
            handled += await retry_stuck(redis, handlers, compensations, consumer=name)
            if handled:
                logger.info("consumer: handled %d message(s)", handled)
        except Exception:
            logger.exception("consumer: pass failed; retrying shortly")
            await asyncio.sleep(1)
