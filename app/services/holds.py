"""Creating holds: "these seats are reserved for you for 5 minutes".

Postgres is asked whether the event and tier can be sold (rarely-changing
facts). Redis then decides, atomically, whether the seats are available
(reserve_tier.lua). Nothing about availability is decided in Python.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    EventNotFound,
    EventNotOnSale,
    HoldLimitExceeded,
    HoldNotFound,
    InvalidSeats,
    InventoryNotReady,
    NoSeatMap,
    SeatingNotSupported,
    SeatTaken,
    SoldOut,
    TierNotFound,
)
from app.core.settings import get_settings
from app.db.models import Event, EventStatus, SeatingType, Tier
from app.db.seat_models import Seat
from app.redis.rehydrate import rehydrate_tier
from app.redis.scripts import (
    HoldRequest,
    HoldStatus,
    ReleaseHoldScript,
    ReleaseOutcome,
    ReserveOutcome,
    ReserveTierScript,
)
from app.redis.seat_scripts import (
    ReserveSeatsScript,
    SeatHoldRequest,
    SeatReserveOutcome,
    rebuild_sold_set,
)


@dataclass(frozen=True)
class Hold:
    hold_id: str
    event_id: int
    tier_id: int
    quantity: int
    expires_at: datetime
    seat_ids: tuple[int, ...] = ()  # reserved seating only


async def create_hold(
    session: AsyncSession,
    redis: Redis,
    *,
    user_id: int,
    event_id: int,
    tier_id: int,
    quantity: int,
    now: datetime | None = None,
) -> Hold:
    """Reserve `quantity` seats in a tier for this user, or raise a typed error."""
    now = now or datetime.now(UTC)
    await _check_tier_is_on_sale(session, event_id, tier_id, now)

    settings = get_settings()
    hold_id = str(uuid.uuid4())
    expires_at = now + timedelta(seconds=settings.hold_ttl_seconds)
    reserve = ReserveTierScript(redis)
    request = HoldRequest(
        hold_id=hold_id,
        event_id=event_id,
        tier_id=tier_id,
        user_id=user_id,
        qty=quantity,
        expires_at_ms=int(expires_at.timestamp() * 1000),
        ttl_seconds=settings.hold_ttl_seconds,
        user_cap=settings.hold_user_cap,
    )
    outcome = await reserve(request)

    if outcome == ReserveOutcome.NOT_INITIALISED:
        # A missing counter is never zero (rule 4): rebuild it from the
        # database (one process at a time), then try exactly once more.
        # The first attempt wrote nothing, so reusing the hold id is safe.
        if await rehydrate_tier(session, redis, event_id, tier_id):
            outcome = await reserve(request)

    if outcome == ReserveOutcome.SOLD_OUT:
        raise SoldOut()
    if outcome == ReserveOutcome.USER_CAP_EXCEEDED:
        raise HoldLimitExceeded()
    if outcome == ReserveOutcome.NOT_INITIALISED:
        # The rebuild didn't finish in time: still never "zero", just "retry".
        raise InventoryNotReady()
    return Hold(hold_id, event_id, tier_id, quantity, expires_at)


async def _check_event_is_on_sale(
    session: AsyncSession, event_id: int, now: datetime
) -> SeatingType:
    event = await session.get(Event, event_id)
    # A draft looks exactly like a missing event, as on the public pages.
    if event is None or event.status == EventStatus.DRAFT:
        raise EventNotFound()
    if event.status != EventStatus.PUBLISHED or event.starts_at <= now:
        raise EventNotOnSale()
    return event.seating


async def _check_tier_is_on_sale(
    session: AsyncSession, event_id: int, tier_id: int, now: datetime
) -> None:
    if await _check_event_is_on_sale(session, event_id, now) != SeatingType.GENERAL_ADMISSION:
        raise SeatingNotSupported()
    tier = await session.get(Tier, tier_id)
    if tier is None or tier.event_id != event_id:
        raise TierNotFound()


async def create_seat_hold(
    session: AsyncSession,
    redis: Redis,
    *,
    user_id: int,
    event_id: int,
    seat_ids: list[int],
    now: datetime | None = None,
) -> Hold:
    """Hold these specific seats (reserved seating), all of them or none. Typed errors otherwise."""
    now = now or datetime.now(UTC)
    if await _check_event_is_on_sale(session, event_id, now) != SeatingType.RESERVED:
        raise NoSeatMap()
    tier_id = await _tier_of_seats(session, event_id, seat_ids)

    settings = get_settings()
    hold_id = str(uuid.uuid4())
    expires_at = now + timedelta(seconds=settings.hold_ttl_seconds)
    reserve = ReserveSeatsScript(redis)
    request = SeatHoldRequest(
        hold_id=hold_id,
        event_id=event_id,
        tier_id=tier_id,
        user_id=user_id,
        seat_ids=seat_ids,
        expires_at_ms=int(expires_at.timestamp() * 1000),
        ttl_seconds=settings.hold_ttl_seconds,
        user_cap=settings.hold_user_cap,
    )
    result = await reserve(request)
    if result.outcome == SeatReserveOutcome.NOT_INITIALISED:
        # A missing sold set is never "nothing sold" (rule 4): build it from
        # Postgres, then try once more (the first attempt wrote nothing).
        if await rebuild_sold_set(session, redis, event_id):
            result = await reserve(request)

    if result.outcome == SeatReserveOutcome.SEAT_TAKEN:
        raise SeatTaken()
    if result.outcome == SeatReserveOutcome.USER_CAP_EXCEEDED:
        raise HoldLimitExceeded()
    if result.outcome == SeatReserveOutcome.NOT_INITIALISED:
        raise InventoryNotReady()
    return Hold(hold_id, event_id, tier_id, len(seat_ids), expires_at, tuple(seat_ids))


async def _tier_of_seats(session: AsyncSession, event_id: int, seat_ids: list[int]) -> int:
    """The one tier all these seats are in. InvalidSeats if any isn't this event's, or tiers mix."""
    rows = (
        await session.execute(
            select(Seat.id, Seat.tier_id).where(Seat.event_id == event_id, Seat.id.in_(seat_ids))
        )
    ).all()
    tiers = {int(row.tier_id) for row in rows}
    # One tier per hold keeps the price simple: tier price x number of seats.
    if len(rows) != len(seat_ids) or len(tiers) != 1:
        raise InvalidSeats()
    return tiers.pop()


async def cancel_hold(redis: Redis, *, user_id: int, hold_id: str) -> None:
    """The user gives their own hold back. Safe to repeat: a second call does nothing.

    Raises HoldNotFound for an unknown hold AND for someone else's hold, so a
    caller can't learn whether another user's hold id exists.
    """
    outcome = await ReleaseHoldScript(redis)(
        hold_id, new_status=HoldStatus.RELEASED, owner_id=user_id
    )
    if outcome in (ReleaseOutcome.NOT_FOUND, ReleaseOutcome.NOT_OWNER):
        raise HoldNotFound()
    if outcome == ReleaseOutcome.KEY_MISMATCH:
        # The hold record doesn't match its own keys: a bug, never user error.
        raise RuntimeError(f"hold {hold_id} record does not match its keys")
    # RELEASED or ALREADY_FINISHED: either way, the hold no longer holds seats.
