"""The per-user hold cap (10 seats per event) can't be bypassed by firing many holds at once.

Each request alone is within the limit; only the shared, atomic count in
Redis (uhold:{event}:{user}, checked inside reserve_tier.lua) stops them adding
up to more (CLAUDE.md section 9: "repeated hold calls must not bypass it").
"""

import asyncio

import pytest
from httpx import AsyncClient, Response
from redis.asyncio import Redis

from app.redis.keys import inventory_key, user_hold_key
from tests.sales import Sale, hold


async def fire_together(
    client: AsyncClient, sale: Sale, user_id: int, quantities: list[int]
) -> list[Response]:
    start = asyncio.Event()

    async def one(quantity: int) -> Response:
        await start.wait()
        return await hold(client, sale, user_id=user_id, quantity=quantity)

    tasks = [asyncio.create_task(one(q)) for q in quantities]
    await asyncio.sleep(0)
    start.set()
    return await asyncio.gather(*tasks)


@pytest.mark.parametrize(
    ("quantities", "expected_held"),
    [
        ([1] * 20, 10),  # 20 single seats: exactly 10 allowed
        ([3] * 8, 9),  # 3+3+3 = 9; a 4th would make 12
        ([10, 10, 10], 10),  # only one full-size hold fits
    ],
)
async def test_one_user_firing_many_holds_at_once_stays_within_the_cap(
    client: AsyncClient,
    redis: Redis,
    sale: Sale,
    quantities: list[int],
    expected_held: int,
) -> None:
    responses = await fire_together(client, sale, user_id=7, quantities=quantities)

    held = sum(q for q, r in zip(quantities, responses, strict=True) if r.status_code == 201)
    refused = [r for r in responses if r.status_code != 201]
    assert held == expected_held
    # Every refusal is specifically the cap, not "sold out" or an error.
    assert {r.json()["error"] for r in refused} == {"hold_limit_exceeded"}
    # Redis agrees with what the API said.
    assert await redis.get(user_hold_key(sale.event_id, 7)) == str(expected_held)
    assert await redis.get(inventory_key(sale.event_id, sale.tier_id)) == str(50 - expected_held)
