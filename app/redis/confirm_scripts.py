"""Python wrappers for the order Lua scripts: consume, revert and finish a hold; return seats."""

import enum
from collections.abc import Sequence
from dataclasses import dataclass

from redis.asyncio import Redis

from app.redis.keys import (
    HOLDS_CONFIRMING_KEY,
    HOLDS_EXPIRY_KEY,
    hold_key,
    inventory_key,
    seat_key,
    seats_returned_key,
    sold_seats_key,
    user_hold_key,
)
from app.redis.live import mark_changed
from app.redis.scripts import LUA_DIR

CONSUME_HOLD_LUA = (LUA_DIR / "consume_hold.lua").read_text()
REVERT_HOLD_LUA = (LUA_DIR / "revert_hold.lua").read_text()
FINISH_HOLD_LUA = (LUA_DIR / "finish_hold.lua").read_text()
RETURN_SEATS_LUA = (LUA_DIR / "return_seats.lua").read_text()


class ConsumeOutcome(enum.Enum):
    STARTED = 1
    NOT_FOUND = -1
    NOT_OWNER = -2
    ALREADY_CONFIRMING = -3
    EXPIRED = -4


@dataclass(frozen=True)
class ConsumedHold:
    outcome: ConsumeOutcome
    # Only set when outcome is STARTED: the hold's own, server-side facts.
    event_id: int = 0
    tier_id: int = 0
    quantity: int = 0
    seat_ids: tuple[int, ...] = ()  # reserved seating only


class ConsumeHoldScript:
    """HELD -> CONFIRMING for the hold's owner, returning the hold's own details."""

    def __init__(self, redis: Redis) -> None:
        self._script = redis.register_script(CONSUME_HOLD_LUA)

    async def __call__(
        self, hold_id: str, *, user_id: int, now_ms: int, grace_ms: int
    ) -> ConsumedHold:
        result = await self._script(
            keys=[hold_key(hold_id), HOLDS_EXPIRY_KEY, HOLDS_CONFIRMING_KEY],
            args=[hold_id, str(user_id), now_ms, grace_ms],
        )
        outcome = ConsumeOutcome(int(result[0]))
        if outcome != ConsumeOutcome.STARTED:
            return ConsumedHold(outcome)
        seats = tuple(int(seat) for seat in str(result[4]).split(",") if seat)
        return ConsumedHold(
            outcome,
            event_id=int(result[1]),
            tier_id=int(result[2]),
            quantity=int(result[3]),
            seat_ids=seats,
        )


class RevertHoldScript:
    """CONFIRMING -> HELD, when confirming fails. Returns True if it reverted."""

    def __init__(self, redis: Redis) -> None:
        self._script = redis.register_script(REVERT_HOLD_LUA)

    async def __call__(self, hold_id: str) -> bool:
        result = await self._script(
            keys=[hold_key(hold_id), HOLDS_EXPIRY_KEY, HOLDS_CONFIRMING_KEY], args=[hold_id]
        )
        return int(result) == 1


class FinishOutcome(enum.Enum):
    FINISHED = 1
    NOT_CONFIRMING = 0
    NOT_FOUND = -1
    KEY_MISMATCH = -4


class FinishHoldScript:
    """CONFIRMING -> CONSUMED once tickets are issued. Safe to run any number of times."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._script = redis.register_script(FINISH_HOLD_LUA)

    async def __call__(
        self, hold_id: str, *, event_id: int, user_id: int, seat_ids: Sequence[int] = ()
    ) -> FinishOutcome:
        result = await self._script(
            keys=[
                hold_key(hold_id),
                HOLDS_CONFIRMING_KEY,
                user_hold_key(event_id, user_id),
                sold_seats_key(event_id),
                *(seat_key(event_id, seat) for seat in seat_ids),
            ],
            args=[hold_id, str(event_id), str(user_id), *seat_ids],
        )
        outcome = FinishOutcome(int(result))
        if outcome == FinishOutcome.FINISHED:
            await mark_changed(self._redis, event_id)
        return outcome


class ReturnOutcome(enum.Enum):
    RETURNED = 1
    ALREADY_RETURNED = 0
    COUNTER_MISSING = -1


# Long enough to outlive any redelivery of the same message.
RETURN_MARKER_SECONDS = 7 * 24 * 3600


class ReturnSeatsScript:
    """Put a cancelled order's seats back on sale (counter or sold set), once per order."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._script = redis.register_script(RETURN_SEATS_LUA)

    async def __call__(
        self,
        order_id: str,
        *,
        event_id: int,
        tier_id: int,
        quantity: int,
        seat_ids: Sequence[int] = (),
    ) -> ReturnOutcome:
        result = await self._script(
            keys=[
                inventory_key(event_id, tier_id),
                seats_returned_key(order_id),
                sold_seats_key(event_id),
            ],
            args=[quantity, RETURN_MARKER_SECONDS, *seat_ids],
        )
        outcome = ReturnOutcome(int(result))
        if outcome == ReturnOutcome.RETURNED:
            await mark_changed(self._redis, event_id)
        return outcome
