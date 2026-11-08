"""release_hold.lua tested in isolation against a real Redis: seats come back exactly once."""

import asyncio
import time

from redis.asyncio import Redis

from app.redis.keys import HOLDS_EXPIRY_KEY, hold_key, inventory_key, user_hold_key
from app.redis.scripts import (
    HoldRequest,
    HoldStatus,
    ReleaseHoldScript,
    ReleaseOutcome,
    ReserveOutcome,
    ReserveTierScript,
)

EVENT, TIER, USER = 1, 10, 7
INV = inventory_key(EVENT, TIER)
UHOLD = user_hold_key(EVENT, USER)


async def make_hold(
    redis: Redis, hold_id: str = "h1", qty: int = 2, expires_in_s: int = 300
) -> int:
    """Reserve a hold from 10 seats; returns its expires_at in ms."""
    if not await redis.exists(INV):
        await redis.set(INV, 10)
    expires_at_ms = int(time.time() * 1000) + expires_in_s * 1000
    outcome = await ReserveTierScript(redis)(
        HoldRequest(hold_id, EVENT, TIER, USER, qty, expires_at_ms, 300, user_cap=10)
    )
    assert outcome == ReserveOutcome.RESERVED
    return expires_at_ms


async def test_releasing_returns_the_seats_and_clears_the_user_count(redis: Redis) -> None:
    await make_hold(redis, qty=3)
    assert await redis.get(INV) == "7"

    outcome = await ReleaseHoldScript(redis)("h1", new_status=HoldStatus.RELEASED, owner_id=USER)

    assert outcome == ReleaseOutcome.RELEASED
    assert await redis.get(INV) == "10"
    assert await redis.exists(UHOLD) == 0  # back to zero means the key is gone
    assert await redis.hget(hold_key("h1"), "status") == "RELEASED"
    assert await redis.zscore(HOLDS_EXPIRY_KEY, "h1") is None


async def test_releasing_twice_returns_the_seats_only_once(redis: Redis) -> None:
    await make_hold(redis, qty=3)
    release = ReleaseHoldScript(redis)

    first = await release("h1", new_status=HoldStatus.RELEASED, owner_id=USER)
    second = await release("h1", new_status=HoldStatus.RELEASED, owner_id=USER)

    assert (first, second) == (ReleaseOutcome.RELEASED, ReleaseOutcome.ALREADY_FINISHED)
    assert await redis.get(INV) == "10"  # not 13


async def test_ten_simultaneous_releases_return_the_seats_only_once(redis: Redis) -> None:
    await make_hold(redis, qty=3)
    release = ReleaseHoldScript(redis)
    start = asyncio.Event()

    async def one() -> ReleaseOutcome:
        await start.wait()
        return await release("h1", new_status=HoldStatus.RELEASED, owner_id=USER)

    tasks = [asyncio.create_task(one()) for _ in range(10)]
    await asyncio.sleep(0)
    start.set()
    outcomes = await asyncio.gather(*tasks)

    assert outcomes.count(ReleaseOutcome.RELEASED) == 1
    assert outcomes.count(ReleaseOutcome.ALREADY_FINISHED) == 9
    assert await redis.get(INV) == "10"


async def test_someone_elses_hold_is_untouched(redis: Redis) -> None:
    await make_hold(redis, qty=3)

    outcome = await ReleaseHoldScript(redis)("h1", new_status=HoldStatus.RELEASED, owner_id=999)

    assert outcome == ReleaseOutcome.NOT_OWNER
    assert await redis.get(INV) == "7"
    assert await redis.hget(hold_key("h1"), "status") == "HELD"


async def test_an_unknown_hold_is_not_found(redis: Redis) -> None:
    outcome = await ReleaseHoldScript(redis)("nope", new_status=HoldStatus.RELEASED, owner_id=USER)

    assert outcome == ReleaseOutcome.NOT_FOUND


async def test_sweeper_mode_leaves_unexpired_holds_alone(redis: Redis) -> None:
    expires_at = await make_hold(redis, qty=2)
    release = ReleaseHoldScript(redis)

    too_early = await release(
        "h1", new_status=HoldStatus.EXPIRED, owner_id=None, only_if_expired_at_ms=expires_at - 1
    )
    on_time = await release(
        "h1", new_status=HoldStatus.EXPIRED, owner_id=None, only_if_expired_at_ms=expires_at
    )

    assert too_early == ReleaseOutcome.NOT_EXPIRED
    assert on_time == ReleaseOutcome.RELEASED
    assert await redis.hget(hold_key("h1"), "status") == "EXPIRED"


async def test_a_missing_counter_is_not_recreated_by_a_release(redis: Redis) -> None:
    await make_hold(redis, qty=2)
    await redis.delete(INV)  # e.g. Redis lost the counter

    outcome = await ReleaseHoldScript(redis)("h1", new_status=HoldStatus.RELEASED, owner_id=USER)

    assert outcome == ReleaseOutcome.RELEASED
    # Creating it as "2" would be a lie; it must be rebuilt from the DB (S2.8).
    assert await redis.exists(INV) == 0
    assert await redis.exists(UHOLD) == 0


async def test_the_user_count_never_goes_negative(redis: Redis) -> None:
    await make_hold(redis, qty=3)
    await redis.set(UHOLD, 1)  # simulate a count that drifted low

    await ReleaseHoldScript(redis)("h1", new_status=HoldStatus.RELEASED, owner_id=USER)

    assert await redis.exists(UHOLD) == 0  # not -2


async def test_the_user_count_has_a_safety_expiry(redis: Redis) -> None:
    await make_hold(redis, qty=2)

    # Hold lifetime (300 s) + 900 s grace: a missed release can't strand a user.
    assert 300 + 890 < await redis.ttl(UHOLD) <= 300 + 900
