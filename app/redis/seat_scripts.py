"""Python side of reserved seating in Redis: reserve_seats.lua and the sold-set rebuild.

`sold:{event}` lists the seats that can't be held: those with an ISSUED
ticket, plus (after a rebuild) those claimed by PENDING orders, whose hold
keys may be gone. It always contains SOLD_SET_MARKER once built, so a missing
set means "not built yet", never "nothing sold" (rule 4).
"""

import enum
from dataclasses import dataclass

from redis.asyncio import Redis
from redis.exceptions import LockError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.order_models import Order, OrderStatus, Ticket, TicketStatus
from app.redis.keys import HOLDS_EXPIRY_KEY, hold_key, seat_key, sold_seats_key, user_hold_key
from app.redis.live import mark_changed
from app.redis.scripts import LUA_DIR

RESERVE_SEATS_LUA = (LUA_DIR / "reserve_seats.lua").read_text()
# Not a seat id (those are positive numbers), so it can never block a real seat.
SOLD_SET_MARKER = "built"
REBUILD_LOCK_SECONDS = 10
REBUILD_WAIT_SECONDS = 2


class SeatReserveOutcome(enum.Enum):
    RESERVED = 1
    SEAT_TAKEN = -1
    NOT_INITIALISED = -2
    USER_CAP_EXCEEDED = -3


@dataclass(frozen=True)
class SeatReserveResult:
    outcome: SeatReserveOutcome
    taken_seat_id: int | None = None  # set for SEAT_TAKEN


@dataclass(frozen=True)
class SeatHoldRequest:
    hold_id: str
    event_id: int
    tier_id: int
    user_id: int
    seat_ids: list[int]
    expires_at_ms: int
    ttl_seconds: int
    user_cap: int


class ReserveSeatsScript:
    """Hold all the requested seats, or none. See app/redis/lua/reserve_seats.lua."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._script = redis.register_script(RESERVE_SEATS_LUA)

    async def __call__(self, request: SeatHoldRequest) -> SeatReserveResult:
        if not request.seat_ids or len(set(request.seat_ids)) != len(request.seat_ids):
            raise ValueError("seat_ids must be non-empty and distinct")
        keys = [
            hold_key(request.hold_id),
            HOLDS_EXPIRY_KEY,
            user_hold_key(request.event_id, request.user_id),
            sold_seats_key(request.event_id),
            *(seat_key(request.event_id, seat_id) for seat_id in request.seat_ids),
        ]
        args: list[str | int] = [
            request.hold_id,
            request.user_id,
            request.expires_at_ms,
            request.user_cap,
            request.ttl_seconds,
            request.event_id,
            request.tier_id,
            *request.seat_ids,
        ]
        result = await self._script(keys=keys, args=args)
        outcome = SeatReserveOutcome(int(result[0]))
        taken = int(result[1]) if outcome == SeatReserveOutcome.SEAT_TAKEN else None
        if outcome == SeatReserveOutcome.RESERVED:
            await mark_changed(self._redis, request.event_id)
        return SeatReserveResult(outcome, taken)


async def sold_seat_ids(session: AsyncSession, event_id: int) -> set[int]:
    """Seats with an ISSUED ticket: the ones that can never be held again."""
    rows = await session.scalars(
        select(Ticket.seat_id).where(
            Ticket.event_id == event_id,
            Ticket.status == TicketStatus.ISSUED,
            Ticket.seat_id.is_not(None),
        )
    )
    return {seat_id for seat_id in rows if seat_id is not None}


async def seats_in_pending_orders(session: AsyncSession, event_id: int) -> set[int]:
    """Seats claimed by PENDING orders (bought, tickets not issued yet)."""
    rows = await session.scalars(
        select(Order.seat_ids).where(
            Order.event_id == event_id,
            Order.status == OrderStatus.PENDING,
            Order.seat_ids.is_not(None),
        )
    )
    return {seat for seats in rows if seats for seat in seats}


async def unmark_sold(redis: Redis, event_id: int, seat_ids: set[int]) -> None:
    """Take seats out of the sold set (never creates the set)."""
    key = sold_seats_key(event_id)
    if await redis.exists(key):
        await redis.srem(key, *(str(seat) for seat in seat_ids))


async def rebuild_sold_set(
    session: AsyncSession, redis: Redis, event_id: int, *, force: bool = False
) -> bool:
    """Build `sold:{event}` from Postgres if it's missing (or always, with force). True if done.

    One process rebuilds at a time (a lock), like counter rehydration (S2.8);
    the others wait briefly for it to appear. The set is replaced in one
    MULTI/EXEC transaction, so nobody ever sees it half-built.
    """
    key = sold_seats_key(event_id)
    lock = redis.lock(
        f"lock:rebuild-sold:{event_id}",
        timeout=REBUILD_LOCK_SECONDS,
        blocking_timeout=REBUILD_WAIT_SECONDS,
    )
    if not await lock.acquire():
        return bool(await redis.exists(key))
    try:
        if force or not await redis.exists(key):
            taken = await sold_seat_ids(session, event_id)
            taken |= await seats_in_pending_orders(session, event_id)
            # DEL + one SADD (the marker and every taken seat) as one
            # transaction: the set is complete or absent, never half-built.
            async with redis.pipeline(transaction=True) as pipe:
                pipe.delete(key)
                pipe.sadd(key, SOLD_SET_MARKER, *(str(seat) for seat in taken))
                await pipe.execute()
    finally:
        try:
            await lock.release()
        except LockError:
            pass
    return True
