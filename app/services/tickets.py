"""Issuing tickets for a PENDING order, with the database as the final guard (CLAUDE.md section 6).

Redis already reserved the seats, but Postgres is the source of truth: one
conditional UPDATE both counts the seats as sold and hands out ticket
numbers, and it refuses outright if that would pass the tier's capacity.
No read-then-write, no shared lock held while thinking, no version column.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.job_errors import InvariantViolation, PermanentError
from app.db.order_models import Order, OrderStatus, Ticket
from app.services.auth import violated_constraint

# Atomic: the capacity check and the increment happen in one statement, so
# two workers can't both read "49 sold" and both write "50". Postgres locks
# just this tier row for the instant of the UPDATE.
TAKE_SEATS = text(
    "UPDATE tiers"
    "   SET sold = sold + :q, next_number = next_number + :q"
    " WHERE id = :tier AND sold + :q <= capacity"
    " RETURNING next_number"
)


@dataclass(frozen=True)
class IssuedTickets:
    order_id: uuid.UUID
    ticket_numbers: list[int]


async def issue_tickets(session: AsyncSession, order_id: uuid.UUID) -> IssuedTickets | None:
    """Issue the order's tickets and mark it CONFIRMED, inside the caller's transaction.

    Returns None if the order is no longer PENDING (nothing to do). Raises
    InvariantViolation if the tier would go past capacity: the backstop
    fired, and nothing is written. Quantity and tier come from the order
    row, never from the message (rule 1).
    """
    # FOR UPDATE: if anything else changes this order at the same moment
    # (a cancel, S5.3), one of us waits for the other.
    order = await session.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if order is None:
        raise PermanentError(f"order {order_id} does not exist")
    if order.status != OrderStatus.PENDING:
        return None

    last_number = await session.scalar(TAKE_SEATS, {"q": order.quantity, "tier": order.tier_id})
    if last_number is None:
        raise InvariantViolation(
            f"tier {order.tier_id} has no room for order {order_id} ({order.quantity} seats)"
        )

    # This order owns the numbers just handed out: next_number - q + 1 .. next_number.
    first_number = last_number - order.quantity + 1
    numbers = list(range(first_number, last_number + 1))
    # Reserved seating: ticket n is for seat n of the order. General admission: no seat.
    seats: list[int | None] = list(order.seat_ids or []) or [None] * order.quantity
    if len(seats) != order.quantity:
        raise PermanentError(
            f"order {order_id} has {len(seats)} seats for {order.quantity} tickets"
        )
    session.add_all(
        Ticket(
            order_id=order.id,
            event_id=order.event_id,
            tier_id=order.tier_id,
            seat_id=seat_id,
            ticket_number=number,
        )
        for number, seat_id in zip(numbers, seats, strict=True)
    )
    order.status = OrderStatus.CONFIRMED
    try:
        await session.flush()  # surface any constraint error here, inside this transaction
    except IntegrityError as error:
        if violated_constraint(error) == "uq_tickets_issued_seat":
            # A seat that already has a live ticket: the last line of defence
            # against double-selling a seat fired. Nothing is written.
            raise InvariantViolation(f"order {order_id}: a seat already has a ticket") from error
        raise
    return IssuedTickets(order.id, numbers)
