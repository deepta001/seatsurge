"""Python wrappers for the Lua scripts in app/redis/lua/.

Each wrapper loads its script once, calls it with the right KEYS and ARGV,
and turns the script's numeric return code into a named outcome, so callers
never deal with magic numbers like -3.
"""

import enum
from dataclasses import dataclass
from pathlib import Path

from redis.asyncio import Redis

from app.redis.keys import HOLDS_EXPIRY_KEY, hold_key, inventory_key, user_hold_key

LUA_DIR = Path(__file__).parent / "lua"


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
        self._script = redis.register_script((LUA_DIR / "reserve_tier.lua").read_text())

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
