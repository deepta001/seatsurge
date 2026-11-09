"""The seat map of a reserved-seating event: every seat and whether it's free (S6.1).

Each seat's state comes from where the truth lives:
- SOLD: Postgres has an ISSUED ticket for it (the source of truth).
- HELD: Redis has a `seat:{event}:{seat_id}` key for it (a live hold, S6.2).
- AVAILABLE: neither.
A seat that is both (should never happen) is reported SOLD.
"""

import enum
from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NoSeatMap
from app.db.models import SeatingType
from app.db.order_models import Ticket, TicketStatus
from app.db.seat_models import Seat
from app.redis.keys import seat_key
from app.services.events import get_public_event

# One MGET per this many seats, so a big map never sends one enormous command.
MGET_CHUNK = 1000


class SeatState(enum.StrEnum):
    AVAILABLE = "AVAILABLE"
    HELD = "HELD"
    SOLD = "SOLD"


@dataclass(frozen=True)
class SeatView:
    seat_id: int
    tier_id: int
    label: str
    state: SeatState


async def held_seat_ids(redis: Redis, event_id: int, seat_ids: list[int]) -> set[int]:
    held: set[int] = set()
    for start in range(0, len(seat_ids), MGET_CHUNK):
        chunk = seat_ids[start : start + MGET_CHUNK]
        values = await redis.mget([seat_key(event_id, seat_id) for seat_id in chunk])
        held.update(seat_id for seat_id, value in zip(chunk, values, strict=True) if value)
    return held


async def get_seat_map(session: AsyncSession, redis: Redis, event_id: int) -> list[SeatView]:
    """All seats of a published (or cancelled) reserved-seating event, in id order.

    Raises EventNotFound (unknown or draft) or NoSeatMap (general admission).
    """
    event = (await get_public_event(session, event_id)).event
    if event.seating != SeatingType.RESERVED:
        raise NoSeatMap()

    seats = (
        await session.execute(
            select(Seat.id, Seat.tier_id, Seat.label)
            .where(Seat.event_id == event_id)
            .order_by(Seat.id)
        )
    ).all()
    sold = set(
        await session.scalars(
            select(Ticket.seat_id).where(
                Ticket.event_id == event_id,
                Ticket.status == TicketStatus.ISSUED,
                Ticket.seat_id.is_not(None),
            )
        )
    )
    held = await held_seat_ids(redis, event_id, [seat.id for seat in seats])

    def state_of(seat_id: int) -> SeatState:
        if seat_id in sold:
            return SeatState.SOLD
        if seat_id in held:
            return SeatState.HELD
        return SeatState.AVAILABLE

    return [SeatView(s.id, s.tier_id, s.label, state_of(s.id)) for s in seats]
