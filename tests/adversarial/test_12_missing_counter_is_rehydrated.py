"""Adversarial test 12: a missing Redis counter is rebuilt from the source of truth, never zero.

available = capacity - sold (Postgres) - seats in active holds (Redis)
            (- seats in pending orders, from Phase C)
"""

import asyncio

import pytest
from httpx import AsyncClient, Response
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.redis import rehydrate
from app.redis.keys import inventory_key, rehydrate_lock_key
from tests.sales import Sale, bearer, hold


def counter(sale: Sale) -> str:
    return inventory_key(sale.event_id, sale.tier_id)


async def set_sold(db_engine: AsyncEngine, sale: Sale, sold: int) -> None:
    async with db_engine.begin() as connection:
        await connection.execute(
            text("UPDATE tiers SET sold = :sold WHERE id = :tier"),
            {"sold": sold, "tier": sale.tier_id},
        )


async def test_a_missing_counter_is_rebuilt_not_treated_as_zero(
    client: AsyncClient, redis: Redis, sale: Sale
) -> None:
    await redis.delete(counter(sale))

    response = await hold(client, sale, quantity=3)

    assert response.status_code == 201  # not 409 sold_out, not 503
    assert await redis.get(counter(sale)) == "47"  # 50 capacity - 3 just held


async def test_the_rebuild_subtracts_active_holds_and_db_sales(
    client: AsyncClient, redis: Redis, db_engine: AsyncEngine, sale: Sale
) -> None:
    await hold(client, sale, user_id=1, quantity=10)  # active: counted
    released = (await hold(client, sale, user_id=2, quantity=5)).json()["hold_id"]
    await client.delete(f"/holds/{released}", headers=bearer(2))  # released: not counted
    await set_sold(db_engine, sale, 20)  # e.g. confirmed sales in Postgres
    await redis.delete(counter(sale))

    response = await hold(client, sale, user_id=3, quantity=1)

    assert response.status_code == 201
    # 50 capacity - 20 sold - 10 held (user 1) - 1 just held (user 3) = 19
    assert await redis.get(counter(sale)) == "19"


async def test_a_genuinely_sold_out_tier_rebuilds_to_a_real_zero(
    client: AsyncClient, redis: Redis, db_engine: AsyncEngine, sale: Sale
) -> None:
    await set_sold(db_engine, sale, 50)
    await redis.delete(counter(sale))

    response = await hold(client, sale)

    assert response.status_code == 409
    assert response.json()["error"] == "sold_out"
    assert await redis.get(counter(sale)) == "0"  # zero computed from the DB, not assumed


async def test_fifty_simultaneous_requests_rebuild_once_and_never_oversell(
    client: AsyncClient, redis: Redis, sale: Sale, monkeypatch: pytest.MonkeyPatch
) -> None:
    rebuilds = 0
    real_compute = rehydrate.compute_available

    async def counting_compute(*args: object, **kwargs: object) -> int:
        nonlocal rebuilds
        rebuilds += 1
        await asyncio.sleep(0.05)  # make the rebuild slow enough for others to pile up
        return await real_compute(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(rehydrate, "compute_available", counting_compute)
    await redis.delete(counter(sale))
    start = asyncio.Event()

    async def buyer(user_id: int) -> Response:
        await start.wait()
        return await hold(client, sale, user_id=user_id, quantity=2)

    tasks = [asyncio.create_task(buyer(u)) for u in range(1, 51)]
    await asyncio.sleep(0)
    start.set()
    responses = await asyncio.gather(*tasks)

    assert rebuilds == 1  # single-flight: one rebuild for 50 requests
    created = [r for r in responses if r.status_code == 201]
    refused = [r for r in responses if r.status_code != 201]
    assert len(created) == 25  # 50 seats / 2 each
    assert {r.json()["error"] for r in refused} == {"sold_out"}
    assert await redis.get(counter(sale)) == "0"


async def test_if_the_rebuild_never_finishes_the_answer_is_503_not_zero(
    client: AsyncClient, redis: Redis, sale: Sale, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Another process "holds" the rebuild lock and never finishes.
    monkeypatch.setattr(rehydrate, "WAIT_SECONDS", 0.2)
    await redis.delete(counter(sale))
    await redis.set(rehydrate_lock_key(sale.event_id, sale.tier_id), "someone-else", ex=10)

    response = await hold(client, sale)

    assert response.status_code == 503
    assert response.json()["error"] == "inventory_not_ready"
    assert await redis.exists(counter(sale)) == 0  # still not invented
