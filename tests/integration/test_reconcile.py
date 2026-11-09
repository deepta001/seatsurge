"""POST /admin/events/{id}/reconcile: rebuild counters from Postgres + live holds, overwriting."""

import asyncio
from typing import Any

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.tokens import create_access_token
from app.db.models import UserRole
from app.redis import rehydrate
from app.redis.keys import hold_key, inventory_key
from app.services.payments import MockPaymentProvider
from tests.outbox import run_pipeline
from tests.sales import Sale, bearer, confirm, hold


def admin(sale: Sale) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sale.admin_id, UserRole.ADMIN)}"}


async def reconcile(client: AsyncClient, sale: Sale) -> Any:
    response = await client.post(f"/admin/events/{sale.event_id}/reconcile", headers=admin(sale))
    assert response.status_code == 200, response.text
    [tier] = response.json()["tiers"]
    assert tier["tier_id"] == sale.tier_id
    return tier


async def counter(redis: Redis, sale: Sale) -> int:
    return int(await redis.get(inventory_key(sale.event_id, sale.tier_id)) or -1)


async def place_order(client: AsyncClient, sale: Sale, user_id: int, quantity: int) -> str:
    held = await hold(client, sale, user_id=user_id, quantity=quantity)
    assert held.status_code == 201
    assert (await confirm(client, held.json()["hold_id"], user_id)).status_code == 202
    return str(held.json()["hold_id"])


async def test_only_admins_can_reconcile(client: AsyncClient, sale: Sale) -> None:
    url = f"/admin/events/{sale.event_id}/reconcile"
    assert (await client.post(url)).status_code == 401
    assert (await client.post(url, headers=bearer(1))).status_code == 403
    missing = await client.post("/admin/events/999999/reconcile", headers=admin(sale))
    assert missing.status_code == 404


async def test_a_wrong_counter_is_overwritten_with_the_truth(
    client: AsyncClient, sale: Sale, redis: Redis
) -> None:
    assert (await hold(client, sale, user_id=1, quantity=3)).status_code == 201
    await redis.set(inventory_key(sale.event_id, sale.tier_id), 999)  # drifted

    assert await reconcile(client, sale) == {"tier_id": sale.tier_id, "before": 999, "after": 47}
    assert await counter(redis, sale) == 47


async def test_a_missing_counter_is_rebuilt(client: AsyncClient, sale: Sale, redis: Redis) -> None:
    await redis.delete(inventory_key(sale.event_id, sale.tier_id))

    assert await reconcile(client, sale) == {"tier_id": sale.tier_id, "before": None, "after": 50}


async def test_sold_pending_and_held_seats_are_all_counted_even_with_a_lost_hold(
    client: AsyncClient,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
    redis: Redis,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await place_order(client, sale, buyers[0], quantity=2)
    await run_pipeline(sessions, redis)  # 2 sold (tickets issued)
    pending_hold = await place_order(client, sale, buyers[1], quantity=3)  # 3 PENDING
    assert (await hold(client, sale, user_id=buyers[2], quantity=4)).status_code == 201  # 4 held
    await redis.set(inventory_key(sale.event_id, sale.tier_id), 50)  # drifted

    assert (await reconcile(client, sale))["after"] == 50 - 2 - 3 - 4

    # Redis loses the pending order's hold record: Postgres still knows the order.
    await redis.delete(hold_key(pending_hold))
    assert (await reconcile(client, sale))["after"] == 50 - 2 - 3 - 4


async def test_an_order_finishing_mid_reconcile_is_never_missed(
    client: AsyncClient,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
    redis: Redis,
    sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await place_order(client, sale, buyers[0], quantity=3)
    real_active_holds = rehydrate.active_holds

    async def worker_finishes_first(*args: Any, **kwargs: Any) -> dict[str, int]:
        # Exactly between reading Postgres and reading Redis, the worker
        # commits the tickets (sold +3, order CONFIRMED) and marks the hold
        # CONSUMED. Those 3 seats must still be counted somewhere.
        monkeypatch.setattr(rehydrate, "active_holds", real_active_holds)
        await run_pipeline(sessions, redis)
        return await real_active_holds(*args, **kwargs)

    monkeypatch.setattr(rehydrate, "active_holds", worker_finishes_first)

    assert (await reconcile(client, sale))["after"] == 47  # not 50


async def test_reconciling_during_a_rush_never_oversells(
    client: AsyncClient, sale: Sale, redis: Redis, db_engine: AsyncEngine
) -> None:
    start = asyncio.Event()

    async def buyer(user_id: int) -> int:
        await start.wait()
        response = await hold(client, sale, user_id=user_id, quantity=1)
        return 1 if response.status_code == 201 else 0

    async def admin_reconciles() -> None:
        await start.wait()
        for _ in range(3):  # several times while the buyers are arriving
            await reconcile(client, sale)
            await asyncio.sleep(0)

    buyers = [asyncio.create_task(buyer(n)) for n in range(1, 81)]  # 80 buyers, 50 seats
    reconciler = asyncio.create_task(admin_reconciles())
    start.set()
    held = sum(await asyncio.gather(*buyers))
    await reconciler

    assert held <= 50
    # Every seat is either held or still available: nothing lost, nothing invented.
    assert held + await counter(redis, sale) == 50
