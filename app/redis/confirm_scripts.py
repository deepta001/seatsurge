"""Python wrappers for the confirm-time Lua scripts: consume_hold.lua and revert_hold.lua."""

import enum
from dataclasses import dataclass

from redis.asyncio import Redis

from app.redis.keys import HOLDS_CONFIRMING_KEY, HOLDS_EXPIRY_KEY, hold_key
from app.redis.scripts import LUA_DIR

CONSUME_HOLD_LUA = (LUA_DIR / "consume_hold.lua").read_text()
REVERT_HOLD_LUA = (LUA_DIR / "revert_hold.lua").read_text()


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
        return ConsumedHold(
            outcome, event_id=int(result[1]), tier_id=int(result[2]), quantity=int(result[3])
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
