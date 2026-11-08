"""Adversarial test 5: holds that are created and then abandoned give their seats back after TTL.

Rather than waiting 5 real minutes, the sweeper is told what "now" is.
"""

import asyncio
from datetime import datetime

from httpx import AsyncClient
from redis.asyncio import Redis

from app.redis.keys import HOLDS_EXPIRY_KEY, hold_key, inventory_key, user_hold_key
from app.worker.sweeper import sweep_expired_holds
from tests.sales import Sale, bearer, hold


def ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso).timestamp() * 1000)


async def test_abandoned_holds_return_every_seat_after_they_expire(
    client: AsyncClient, redis: Redis, sale: Sale
) -> None:
    # Five users grab 10 seats each and then vanish (no confirm, no cancel).
    holds = [(await hold(client, sale, user_id=u, quantity=10)).json() for u in range(1, 6)]
    assert await redis.get(inventory_key(sale.event_id, sale.tier_id)) == "0"
    assert (await hold(client, sale, user_id=99)).json()["error"] == "sold_out"
    latest_expiry = max(ms(h["expires_at"]) for h in holds)

    # One millisecond before expiry: nothing is released yet.
    assert await sweep_expired_holds(redis, now=min(ms(h["expires_at"]) for h in holds) - 1) == 0
    # After expiry: every hold is swept.
    released = await sweep_expired_holds(redis, now=latest_expiry)

    assert released == 5
    assert await redis.get(inventory_key(sale.event_id, sale.tier_id)) == "50"
    assert await redis.zcard(HOLDS_EXPIRY_KEY) == 0
    for h, user in zip(holds, range(1, 6), strict=True):
        assert await redis.hget(hold_key(h["hold_id"]), "status") == "EXPIRED"
        assert await redis.exists(user_hold_key(sale.event_id, user)) == 0
    # The seats are genuinely back on sale.
    assert (await hold(client, sale, user_id=99, quantity=10)).status_code == 201


async def test_sweeping_again_changes_nothing(
    client: AsyncClient, redis: Redis, sale: Sale
) -> None:
    h = (await hold(client, sale, quantity=5)).json()
    await sweep_expired_holds(redis, now=ms(h["expires_at"]))

    assert await sweep_expired_holds(redis, now=ms(h["expires_at"]) + 60_000) == 0
    assert await redis.get(inventory_key(sale.event_id, sale.tier_id)) == "50"


async def test_two_sweepers_at_once_never_return_seats_twice(
    client: AsyncClient, redis: Redis, sale: Sale
) -> None:
    holds = [(await hold(client, sale, user_id=u, quantity=2)).json() for u in range(1, 11)]
    now = max(ms(h["expires_at"]) for h in holds)

    counts = await asyncio.gather(*(sweep_expired_holds(redis, now=now) for _ in range(3)))

    assert sum(counts) == 10  # each hold released by exactly one sweeper
    assert await redis.get(inventory_key(sale.event_id, sale.tier_id)) == "50"


async def test_a_user_cancel_racing_the_sweeper_returns_seats_once(
    client: AsyncClient, redis: Redis, sale: Sale
) -> None:
    h = (await hold(client, sale, user_id=3, quantity=6)).json()

    cancel, swept = await asyncio.gather(
        client.delete(f"/holds/{h['hold_id']}", headers=bearer(3)),
        sweep_expired_holds(redis, now=ms(h["expires_at"])),
    )

    assert cancel.status_code == 204
    assert swept in (0, 1)
    assert await redis.get(inventory_key(sale.event_id, sale.tier_id)) == "50"
