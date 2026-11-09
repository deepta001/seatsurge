"""Dead letters: what happens to a message the worker gives up on.

Three steps, in this order, each safe to repeat:
1. Compensate: undo what the message had started (for an order: mark it
   FAILED and give its seats back), so a dead message never leaks seats.
2. Copy the message to `stream:orders:dead` with the reason, for a human.
3. XACK it, so it stops being retried.
If step 1 or 2 fails, nothing is acked and the whole thing runs again later.
"""

import logging
from collections.abc import Awaitable, Callable, Mapping

from redis.asyncio import Redis

from app.core.job_errors import PermanentError
from app.core.metrics import DEAD_LETTERS
from app.redis.keys import DEAD_LETTER_STREAM_KEY
from app.worker.messages import StreamMessage, parse_message

logger = logging.getLogger(__name__)

# Undo work for one message type, e.g. "order.placed" -> fail the order, release the hold.
Compensation = Callable[[StreamMessage], Awaitable[None]]

MAX_REASON_LENGTH = 500


async def dead_letter(
    redis: Redis,
    compensations: Mapping[str, Compensation],
    *,
    entry_id: str,
    fields: Mapping[str, str],
    reason: str,
    deliveries: int,
    stream: str,
    group: str,
) -> None:
    """Compensate, record in the dead-letter stream, then ack. Raises if a step fails."""
    try:
        message: StreamMessage | None = parse_message(entry_id, fields)
    except PermanentError:
        message = None  # unreadable: nothing we can undo, but still record it

    if message is not None:
        compensate = compensations.get(message.type)
        if compensate is not None:
            await compensate(message)

    record = {
        **fields,
        "dead_entry_id": entry_id,  # lets a human match duplicates of one entry
        "dead_reason": reason[:MAX_REASON_LENGTH],
        "deliveries": str(deliveries),
    }
    await redis.xadd(DEAD_LETTER_STREAM_KEY, record)  # type: ignore[arg-type]
    await redis.xack(stream, group, entry_id)
    # The alert: this counter (graphed and alerted on in Grafana) and an ERROR log.
    DEAD_LETTERS.labels(message.type if message is not None else "unreadable").inc()
    logger.error(
        "consumer: message %s dead-lettered after %d delivery(ies): %s",
        entry_id,
        deliveries,
        reason,
    )
