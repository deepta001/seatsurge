"""Adversarial test 1: N concurrent hold requests on C seats never take more than C.

Built to CLAUDE.md section 11: a start barrier so every request begins
together, far more requesters than seats, multi-seat requests, the specific
error asserted (sold_out, never "any error"), and Redis AND Postgres state
checked afterwards. Runs over HTTP against one app instance; the 3-replica
version behind nginx comes in S8.1 (a 3-process demo is in learning/examples/s2_9).
"""

import asyncio
import random

import pytest
from httpx import AsyncClient, Response
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.redis.keys import HOLDS_EXPIRY_KEY, hold_key, inventory_key, user_hold_key
from tests.sales import Sale, hold

CAPACITY = 50  # the `sale` fixture's tier
BUYERS = 500


@pytest.mark.parametrize("counter_at_start", ["present", "missing"])
@pytest.mark.parametrize("seed", [1, 2])
async def test_500_buyers_wanting_1_to_4_seats_never_take_more_than_50(
    client: AsyncClient,
    redis: Redis,
    db_engine: AsyncEngine,
    sale: Sale,
    counter_at_start: str,
    seed: int,
) -> None:
    if counter_at_start == "missing":
        # The counter must be rebuilt in the middle of the rush (S2.8).
        await redis.delete(inventory_key(sale.event_id, sale.tier_id))
    rng = random.Random(seed)  # seeded, so a failure can be replayed exactly
    wanted = {user_id: rng.randint(1, 4) for user_id in range(1, BUYERS + 1)}
    start = asyncio.Event()

    async def buyer(user_id: int) -> Response:
        await start.wait()  # the start barrier
        return await hold(client, sale, user_id=user_id, quantity=wanted[user_id])

    tasks = {user_id: asyncio.create_task(buyer(user_id)) for user_id in wanted}
    await asyncio.sleep(0)  # let every task reach the barrier
    start.set()
    responses = {user_id: await task for user_id, task in tasks.items()}

    winners = {u: r.json() for u, r in responses.items() if r.status_code == 201}
    losers = {u: r for u, r in responses.items() if r.status_code != 201}
    seats_held = sum(wanted[u] for u in winners)
    left = int(await redis.get(inventory_key(sale.event_id, sale.tier_id)) or -1)

    # 1. Never oversold, and every seat is accounted for.
    assert seats_held <= CAPACITY
    assert seats_held + left == CAPACITY
    # 2. Every refusal is specifically sold_out (not a 500, not a 503).
    assert {r.status_code for r in losers.values()} == {409}
    assert {r.json()["error"] for r in losers.values()} == {"sold_out"}
    # 3. Nobody was refused while their seats were still available. Seats only
    #    go down during the race, so a refusal means they wanted more than is
    #    left even now.
    assert all(wanted[u] > left for u in losers)

    # 4. Redis agrees with itself: one hold record and expiry entry per winner,
    #    with the right quantity, owner and per-user count.
    assert await redis.zcard(HOLDS_EXPIRY_KEY) == len(winners)
    for user_id, body in winners.items():
        record = await redis.hgetall(hold_key(body["hold_id"]))
        assert record["status"] == "HELD"
        assert record["user"] == str(user_id)
        assert int(record["qty"]) == wanted[user_id]
        assert await redis.get(user_hold_key(sale.event_id, user_id)) == str(wanted[user_id])

    # 5. Postgres is untouched by holds: nothing is sold until confirm (Phase C),
    #    and the tier's capacity is what the counter was built from.
    async with db_engine.connect() as connection:
        row = (
            await connection.execute(
                text("SELECT capacity, sold FROM tiers WHERE id = :tier"),
                {"tier": sale.tier_id},
            )
        ).one()
    assert (row.capacity, row.sold) == (CAPACITY, 0)
