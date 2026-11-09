"""The worker's message handlers: what to do with each outbox event type.

`order.placed`: issue the tickets in Postgres (in the run_once transaction),
then, after the commit, mark the Redis hold CONSUMED.
"""

import logging
import uuid

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.job_errors import PermanentError
from app.redis.confirm_scripts import FinishHoldScript, FinishOutcome
from app.services.tickets import issue_tickets
from app.worker.consumer import Handler, StreamMessage
from app.worker.idempotency import run_once

logger = logging.getLogger(__name__)


def payload_int(message: StreamMessage, field: str) -> int:
    try:
        return int(message.payload[field])
    except (KeyError, TypeError, ValueError) as error:
        raise PermanentError(f"message {message.entry_id} has no valid {field!r}") from error


def payload_order_id(message: StreamMessage) -> uuid.UUID:
    try:
        return uuid.UUID(str(message.payload["order_id"]))
    except (KeyError, ValueError) as error:
        raise PermanentError(f"message {message.entry_id} has no valid order_id") from error


async def issue_order_tickets(session: AsyncSession, message: StreamMessage) -> None:
    issued = await issue_tickets(session, payload_order_id(message))
    if issued is None:
        logger.info("worker: order %s is no longer PENDING; nothing to issue", message.aggregate_id)
        return
    logger.info("worker: order %s issued tickets %s", issued.order_id, issued.ticket_numbers)


def finish_hold_after_commit(redis: Redis) -> Handler:
    finish = FinishHoldScript(redis)

    async def finish_hold(message: StreamMessage) -> None:
        outcome = await finish(
            str(message.payload["hold_id"]),
            event_id=payload_int(message, "event_id"),
            user_id=payload_int(message, "user_id"),
        )
        if outcome == FinishOutcome.KEY_MISMATCH:
            # Should never happen: the hold doesn't match its own order. Loud, but
            # the tickets are already committed, so there is nothing to undo.
            logger.error("worker: hold %s does not match its order", message.payload["hold_id"])

    return finish_hold


def build_handlers(
    session_factory: async_sessionmaker[AsyncSession], redis: Redis
) -> dict[str, Handler]:
    """The consumer's handler table: message type -> handler."""
    return {
        "order.placed": run_once(
            session_factory, issue_order_tickets, after_commit=finish_hold_after_commit(redis)
        ),
    }
