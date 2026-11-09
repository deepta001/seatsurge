"""Cancelling a confirmed order (CLAUDE.md section 7.6).

Everything in Postgres happens in ONE transaction: the order and its tickets
become CANCELLED, the tier's `sold` goes down, and an `order.cancelled`
outbox row is written. Redis is NOT touched here (rule 6): the worker gives
the seats back to the Redis counter after reading that outbox row.
"""

import uuid

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import OrderNotCancellable, OrderNotFound
from app.db.order_models import Order, OrderStatus, Ticket, TicketStatus
from app.db.outbox_models import OutboxEvent

ORDER_CANCELLED = "order.cancelled"

# `sold` goes down; `next_number` does NOT, so a cancelled ticket's number is
# never handed out again (section 6). The CHECK (sold >= 0) is the backstop.
RETURN_SEATS = text("UPDATE tiers SET sold = sold - :q WHERE id = :tier")


async def cancel_order(session: AsyncSession, *, user_id: int, order_id: uuid.UUID) -> OrderStatus:
    """Cancel the caller's CONFIRMED order. Cancelling again is harmless. Returns the status.

    Raises OrderNotFound (unknown, or someone else's) or OrderNotCancellable
    (PENDING: the worker may be issuing its tickets right now; or FAILED).
    """
    # FOR UPDATE: two cancels of one order (a double-click) take turns, so the
    # second sees CANCELLED and changes nothing.
    order = await session.scalar(
        select(Order).where(Order.id == order_id, Order.user_id == user_id).with_for_update()
    )
    if order is None:
        raise OrderNotFound()
    if order.status == OrderStatus.CANCELLED:
        await session.rollback()
        return OrderStatus.CANCELLED
    if order.status != OrderStatus.CONFIRMED:
        await session.rollback()
        raise OrderNotCancellable()

    order.status = OrderStatus.CANCELLED
    await session.execute(
        update(Ticket).where(Ticket.order_id == order.id).values(status=TicketStatus.CANCELLED)
    )
    await session.execute(RETURN_SEATS, {"q": order.quantity, "tier": order.tier_id})
    session.add(
        OutboxEvent(
            type=ORDER_CANCELLED,
            aggregate_id=str(order.id),
            payload={
                "order_id": str(order.id),
                "event_id": order.event_id,
                "tier_id": order.tier_id,
                "quantity": order.quantity,
            },
        )
    )
    await session.commit()  # all of it, or none of it
    return OrderStatus.CANCELLED
