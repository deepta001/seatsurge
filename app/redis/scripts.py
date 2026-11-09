"""Python wrappers for the Lua scripts in app/redis/lua/.

Each wrapper loads its script once, calls it with the right KEYS and ARGV,
and turns the script's numeric return code into a named outcome, so callers
never deal with magic numbers like -3.
"""

import enum
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from redis.asyncio import Redis

from app.redis.keys import (
    HOLDS_CONFIRMING_KEY,
    HOLDS_EXPIRY_KEY,
    hold_key,
    inventory_key,
    seat_key,
    user_hold_key,
)

LUA_DIR = Path(__file__).parent / "lua"
# Read once at import, not on every request.
RESERVE_TIER_LUA = (LUA_DIR / "reserve_tier.lua").read_text()
RELEASE_HOLD_LUA = (LUA_DIR / "release_hold.lua").read_text()


class ReserveOutcome(enum.Enum):
    RESERVED = 1
    SOLD_OUT = -1
    NOT_INITIALISED = -2  # the counter is missing: rebuild it from the DB (S2.8)
    USER_CAP_EXCEEDED = -3


@dataclass(frozen=True)
class HoldRequest:
    hold_id: str
    event_id: int
    tier_id: int
    user_id: int
    qty: int
    expires_at_ms: int  # when the hold expires, in Unix milliseconds
    ttl_seconds: int  # the same moment, as "seconds from now"
    user_cap: int  # the most seats one user may hold for this event


class ReserveTierScript:
    """Atomically reserve seats in one tier. See app/redis/lua/reserve_tier.lua."""

    def __init__(self, redis: Redis) -> None:
        # register_script sends the script once and then calls it by its SHA
        # fingerprint (EVALSHA), re-sending it only if Redis has forgotten it.
        self._script = redis.register_script(RESERVE_TIER_LUA)

    async def __call__(self, request: HoldRequest) -> ReserveOutcome:
        if request.qty < 1:
            raise ValueError("qty must be at least 1")
        keys = [
            inventory_key(request.event_id, request.tier_id),
            hold_key(request.hold_id),
            HOLDS_EXPIRY_KEY,
            user_hold_key(request.event_id, request.user_id),
        ]
        args: list[str | int] = [
            request.qty,
            request.hold_id,
            request.user_id,
            request.expires_at_ms,
            request.user_cap,
            request.ttl_seconds,
            request.tier_id,
            request.event_id,
        ]
        code = await self._script(keys=keys, args=args)
        # ReserveOutcome(code) raises ValueError on an unexpected code, which
        # would mean the script and this wrapper are out of step: a bug.
        return ReserveOutcome(int(code))


class ReleaseOutcome(enum.Enum):
    RELEASED = 1
    ALREADY_FINISHED = 0  # released or expired earlier: nothing to do
    NOT_FOUND = -1
    NOT_OWNER = -2
    NOT_EXPIRED = -3  # sweeper mode only
    KEY_MISMATCH = -4  # the record changed between reading it and releasing


class HoldStatus(enum.StrEnum):
    HELD = "HELD"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


def seats_of(record: Mapping[Any, Any]) -> list[str]:
    """The seat ids stored on a hold record ("" or missing for general admission)."""
    raw = str(record.get("seats") or "")
    return [seat for seat in raw.split(",") if seat]


class ReleaseHoldScript:
    """Give a hold's seats back exactly once. See app/redis/lua/release_hold.lua."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._script = redis.register_script(RELEASE_HOLD_LUA)

    async def __call__(
        self,
        hold_id: str,
        *,
        new_status: HoldStatus,
        owner_id: int | None,
        only_if_expired_at_ms: int | None = None,
        include_confirming: bool = False,
    ) -> ReleaseOutcome:
        """Release one hold.

        owner_id: the user who must own it (None = anyone; the sweeper).
        only_if_expired_at_ms: if given, only release if the hold's
        expires_at is at or before this time (the sweeper's "now").
        include_confirming: also release a CONFIRMING hold. Only for the
        worker, after the hold's order was marked FAILED in the database.
        """
        # The inventory and per-user keys depend on the hold's own fields, so
        # read them first. The script re-checks them, so a stale read can't
        # make it touch the wrong counters.
        record = await self._redis.hgetall(hold_key(hold_id))
        if not record:
            await self._redis.zrem(HOLDS_EXPIRY_KEY, hold_id)
            return ReleaseOutcome.NOT_FOUND

        # str(): the client decodes responses to text, but redis-py's type hints
        # also allow bytes, so make it explicit for mypy.
        event_id, tier_id, user_id = str(record["event"]), str(record["tier"]), str(record["user"])
        keys = [
            hold_key(hold_id),
            HOLDS_EXPIRY_KEY,
            inventory_key(int(event_id), int(tier_id)),
            user_hold_key(int(event_id), int(user_id)),
            HOLDS_CONFIRMING_KEY,
            # Reserved seating: the seats this hold has, to free them too (S6.2).
            *(seat_key(int(event_id), int(seat)) for seat in seats_of(record)),
        ]
        args: list[str | int] = [
            hold_id,
            new_status.value,
            "" if owner_id is None else str(owner_id),
            only_if_expired_at_ms or 0,
            "1" if only_if_expired_at_ms is not None else "0",
            event_id,
            tier_id,
            user_id,
            "1" if include_confirming else "0",
        ]
        code = await self._script(keys=keys, args=args)
        return ReleaseOutcome(int(code))
