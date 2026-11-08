"""reserve_tier.lua tested in isolation against a real Redis (CLAUDE.md section 5).

Every refusal must leave Redis exactly as it was (all or nothing), and many
simultaneous buyers must never take more seats than exist.
"""

import asyncio
import random
import time

import pytest
from redis.asyncio import Redis

from app.redis.keys import HOLDS_EXPIRY_KEY, hold_key, inventory_key, user_hold_key
from app.redis.scripts import HoldRequest, ReserveOutcome, ReserveTierScript

EVENT, TIER = 1, 10
INV = inventory_key(EVENT, TIER)
TTL = 300


def request(hold_id: str = "h1", user_id: int = 7, qty: int = 1, cap: int = 10) -> HoldRequest:
    return HoldRequest(
        hold_id=hold_id,
        event_id=EVENT,
        tier_id=TIER,
        user_id=user_id,
        qty=qty,
        expires_at_ms=int(time.time() * 1000) + TTL * 1000,
        ttl_seconds=TTL,
        user_cap=cap,
    )


async def snapshot(redis: Redis) -> dict[str, object]:
    """Everything the script could touch, for "nothing changed" checks."""
    return {
        "keys": sorted(await redis.keys("*")),
        "avail": await redis.get(INV),
        "expiry": await redis.zrange(HOLDS_EXPIRY_KEY, 0, -1, withscores=True),
    }


async def test_a_reservation_writes_every_piece_at_once(redis: Redis) -> None:
    await redis.set(INV, 5)
    reserve = ReserveTierScript(redis)
    req = request(qty=2)

    assert await reserve(req) == ReserveOutcome.RESERVED

    assert await redis.get(INV) == "3"
    assert await redis.get(user_hold_key(EVENT, 7)) == "2"
    assert await redis.hgetall(hold_key("h1")) == {
        "user": "7",
        "event": str(EVENT),
        "tier": str(TIER),
        "qty": "2",
        "status": "HELD",
        "expires_at": str(req.expires_at_ms),
    }
    # The record outlives the hold by 15 minutes (900 s) for the sweeper.
    assert TTL + 890 < await redis.ttl(hold_key("h1")) <= TTL + 900
    assert await redis.zscore(HOLDS_EXPIRY_KEY, "h1") == req.expires_at_ms


async def test_taking_exactly_the_last_seats_works(redis: Redis) -> None:
    await redis.set(INV, 3)

    assert await ReserveTierScript(redis)(request(qty=3)) == ReserveOutcome.RESERVED
    assert await redis.get(INV) == "0"


async def test_sold_out_changes_nothing(redis: Redis) -> None:
    await redis.set(INV, 0)
    before = await snapshot(redis)

    assert await ReserveTierScript(redis)(request()) == ReserveOutcome.SOLD_OUT
    assert await snapshot(redis) == before


async def test_asking_for_more_than_is_left_takes_none_of_them(redis: Redis) -> None:
    await redis.set(INV, 2)
    before = await snapshot(redis)

    # 3 wanted, 2 left: the answer is "no", not "here are 2".
    assert await ReserveTierScript(redis)(request(qty=3)) == ReserveOutcome.SOLD_OUT
    assert await snapshot(redis) == before


async def test_a_missing_counter_is_not_treated_as_zero(redis: Redis) -> None:
    before = await snapshot(redis)

    assert await ReserveTierScript(redis)(request()) == ReserveOutcome.NOT_INITIALISED
    # Nothing written, and crucially the counter was NOT created as 0.
    assert await snapshot(redis) == before
    assert await redis.exists(INV) == 0


async def test_the_per_user_cap_counts_across_holds(redis: Redis) -> None:
    await redis.set(INV, 100)
    reserve = ReserveTierScript(redis)

    assert await reserve(request("h1", qty=3, cap=4)) == ReserveOutcome.RESERVED
    before = await snapshot(redis)
    # 3 held + 2 more = 5, over the cap of 4: refused, nothing changes.
    assert await reserve(request("h2", qty=2, cap=4)) == ReserveOutcome.USER_CAP_EXCEEDED
    assert await snapshot(redis) == before
    # Another user is unaffected by the first user's cap.
    assert await reserve(request("h3", user_id=8, qty=2, cap=4)) == ReserveOutcome.RESERVED


@pytest.mark.parametrize("qty", [0, -1])
async def test_a_non_positive_quantity_is_refused_before_redis(redis: Redis, qty: int) -> None:
    with pytest.raises(ValueError):
        await ReserveTierScript(redis)(request(qty=qty))


async def test_500_simultaneous_buyers_never_take_more_than_50_seats(redis: Redis) -> None:
    """CLAUDE.md section 11: a start barrier, more buyers than seats, multi-seat requests."""
    seats = 50
    await redis.set(INV, seats)
    reserve = ReserveTierScript(redis)
    wanted = [random.randint(1, 3) for _ in range(500)]
    start = asyncio.Event()

    async def buyer(number: int) -> ReserveOutcome:
        await start.wait()
        return await reserve(request(f"hold-{number}", user_id=number, qty=wanted[number]))

    tasks = [asyncio.create_task(buyer(n)) for n in range(500)]
    await asyncio.sleep(0)  # everyone reaches the barrier
    start.set()
    outcomes = await asyncio.gather(*tasks)

    reserved = [n for n, outcome in enumerate(outcomes) if outcome == ReserveOutcome.RESERVED]
    seats_reserved = sum(wanted[n] for n in reserved)
    left = int(await redis.get(INV) or 0)

    # Never oversold, and every seat is accounted for.
    assert seats_reserved <= seats
    assert seats_reserved + left == seats
    assert left >= 0
    # Every failure is specifically "sold out", never some other error.
    assert {o for o in outcomes if o != ReserveOutcome.RESERVED} == {ReserveOutcome.SOLD_OUT}
    # Redis agrees: exactly one hold record and one expiry entry per success.
    assert await redis.zcard(HOLDS_EXPIRY_KEY) == len(reserved)
    held = [int(await redis.hget(hold_key(f"hold-{n}"), "qty") or 0) for n in reserved]
    assert sum(held) == seats_reserved
    # Anyone refused only asked for more than was left at the end.
    assert all(wanted[n] > left for n, o in enumerate(outcomes) if o == ReserveOutcome.SOLD_OUT)
