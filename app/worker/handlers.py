"""The worker's message handlers: what to do with each outbox event type.

`order.placed`: issue the tickets in Postgres (in the run_once transaction),
then, after the commit, mark the Redis hold CONSUMED. If the message is
dead-lettered instead, its compensation marks the order FAILED and gives the
hold's seats back, so a failed order never leaks inventory.

`order.cancelled`: the cancel already committed everything in Postgres;
after checking that, the worker gives the seats back to the Redis counter,
once per order.
"""

import logging
import uuid

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.job_errors import PermanentError
from app.db.order_models import Order, OrderStatus
from app.redis.confirm_scripts import FinishHoldScript, FinishOutcome, ReturnSeatsScript
from app.redis.scripts import HoldStatus, ReleaseHoldScript, ReleaseOutcome
from app.redis.seat_scripts import sold_seat_ids, unmark_sold
from app.services.tickets import issue_tickets
from app.worker.dead_letters import Compensation
from app.worker.idempotency import run_once
from app.worker.messages import Handler, StreamMessage

logger = logging.getLogger(__name__)


def payload_int(message: StreamMessage, field: str) -> int:
    try:
        return int(message.payload[field])
    except (KeyError, TypeError, ValueError) as error:
        raise PermanentError(f"message {message.entry_id} has no valid {field!r}") from error


def payload_seat_ids(message: StreamMessage) -> list[int]:
    """The order's seats (reserved seating), or [] for general admission and older messages."""
    raw = message.payload.get("seat_ids") or []
    try:
        return [int(seat) for seat in raw]
    except (TypeError, ValueError) as error:
        raise PermanentError(f"message {message.entry_id} has invalid seat_ids") from error


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
            seat_ids=payload_seat_ids(message),
        )
        if outcome == FinishOutcome.KEY_MISMATCH:
            # Should never happen: the hold doesn't match its own order. Loud, but
            # the tickets are already committed, so there is nothing to undo.
            logger.error("worker: hold %s does not match its order", message.payload["hold_id"])

    return finish_hold


async def check_order_cancelled(session: AsyncSession, message: StreamMessage) -> None:
    """The cancel did all the database work; make sure it really committed as CANCELLED."""
    order_id = payload_order_id(message)
    order = await session.get(Order, order_id)
    if order is None or order.status != OrderStatus.CANCELLED:
        raise PermanentError(f"order {order_id} is not CANCELLED; not returning its seats")


def return_seats_after_commit(redis: Redis) -> Handler:
    return_seats = ReturnSeatsScript(redis)

    async def give_back(message: StreamMessage) -> None:
        outcome = await return_seats(
            str(payload_order_id(message)),
            event_id=payload_int(message, "event_id"),
            tier_id=payload_int(message, "tier_id"),
            quantity=payload_int(message, "quantity"),
            seat_ids=payload_seat_ids(message),
        )
        logger.info("worker: cancelled order %s seats: %s", message.aggregate_id, outcome.name)

    return give_back


def fail_order_and_release_hold(
    session_factory: async_sessionmaker[AsyncSession], redis: Redis
) -> Compensation:
    """The undo for a dead-lettered `order.placed`: FAILED in the database, then seats back.

    Facts come from the order row, not the message. Only a PENDING order is
    failed; a CONFIRMED one already has tickets, so its seats are never
    released (that would sell them twice). Both steps are idempotent, so a
    dead-letter attempt that crashed halfway can simply run again.
    """
    release = ReleaseHoldScript(redis)

    async def compensate(message: StreamMessage) -> None:
        try:
            order_id = payload_order_id(message)
        except PermanentError:
            logger.error(
                "worker: dead message %s names no order; nothing to undo", message.entry_id
            )
            return
        async with session_factory() as session, session.begin():
            order = await session.scalar(
                select(Order).where(Order.id == order_id).with_for_update()
            )
            if order is None:
                return
            if order.status == OrderStatus.PENDING:
                order.status = OrderStatus.FAILED
            failed = order.status == OrderStatus.FAILED
            hold_id, user_id, event_id = order.hold_id, order.user_id, order.event_id
            # Reserved seating: seats a rebuild may have marked sold for this
            # PENDING order. A seat that DOES have a live ticket (from another
            # order: the double-sell backstop refused this one) stays sold.
            seats_to_free = set(order.seat_ids or []) - await sold_seat_ids(session, event_id)
        if not failed:
            logger.error(
                "worker: dead message for order %s, which is %s; seats kept", order_id, order.status
            )
            return
        # After the commit (rule 6): give the seats back to the Redis counter.
        outcome = await release(
            hold_id, new_status=HoldStatus.RELEASED, owner_id=user_id, include_confirming=True
        )
        if seats_to_free:
            await unmark_sold(redis, event_id, seats_to_free)
        # A real payment provider would be asked for a refund here (the mock
        # lives in the API process, so it can't be reached from the worker).
        logger.error(
            "worker: order %s FAILED; hold %s release: %s", order_id, hold_id, outcome.name
        )
        if outcome == ReleaseOutcome.KEY_MISMATCH:
            logger.error("worker: hold %s does not match order %s", hold_id, order_id)

    return compensate


def build_compensations(
    session_factory: async_sessionmaker[AsyncSession], redis: Redis
) -> dict[str, Compensation]:
    """What to undo when a message of each type is dead-lettered."""
    return {"order.placed": fail_order_and_release_hold(session_factory, redis)}


def build_handlers(
    session_factory: async_sessionmaker[AsyncSession], redis: Redis
) -> dict[str, Handler]:
    """The consumer's handler table: message type -> handler."""
    return {
        "order.placed": run_once(
            session_factory, issue_order_tickets, after_commit=finish_hold_after_commit(redis)
        ),
        "order.cancelled": run_once(
            session_factory, check_order_cancelled, after_commit=return_seats_after_commit(redis)
        ),
    }
