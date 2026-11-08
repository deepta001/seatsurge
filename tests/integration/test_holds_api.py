"""POST /events/{id}/holds over HTTP, with a real Postgres and a real Redis."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient, Response
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.models import EventStatus, SeatingType
from app.redis.keys import hold_key, inventory_key
from tests.sales import Sale, bearer, hold, make_event, new_key


async def test_a_hold_is_created_for_five_minutes(
    client: AsyncClient, redis: Redis, sale: Sale
) -> None:
    response = await hold(client, sale, user_id=42, quantity=3)

    assert response.status_code == 201
    body = response.json()
    assert (body["event_id"], body["tier_id"], body["quantity"]) == (sale.event_id, sale.tier_id, 3)
    expires_in = datetime.fromisoformat(body["expires_at"]) - datetime.now(UTC)
    assert timedelta(minutes=4, seconds=50) < expires_in <= timedelta(minutes=5)
    assert await redis.get(inventory_key(sale.event_id, sale.tier_id)) == "47"
    # The hold belongs to the user from the token, not anything in the body.
    assert await redis.hget(hold_key(body["hold_id"]), "user") == "42"


async def test_asking_for_more_than_is_left_is_sold_out(
    client: AsyncClient, redis: Redis, sale: Sale
) -> None:
    await redis.set(inventory_key(sale.event_id, sale.tier_id), 2)

    response = await hold(client, sale, quantity=3)

    assert response.status_code == 409
    assert response.json()["error"] == "sold_out"
    assert await redis.get(inventory_key(sale.event_id, sale.tier_id)) == "2"


async def test_the_per_user_cap_of_10_spans_several_holds(client: AsyncClient, sale: Sale) -> None:
    assert (await hold(client, sale, user_id=5, quantity=10)).status_code == 201

    response = await hold(client, sale, user_id=5, quantity=1)

    assert response.status_code == 409
    assert response.json()["error"] == "hold_limit_exceeded"


async def test_a_missing_counter_is_503_not_sold_out(
    client: AsyncClient, redis: Redis, sale: Sale
) -> None:
    await redis.delete(inventory_key(sale.event_id, sale.tier_id))

    response = await hold(client, sale)

    assert response.status_code == 503
    assert response.json()["error"] == "inventory_not_ready"
    assert response.headers["Retry-After"] == "1"


async def test_holding_requires_a_login(client: AsyncClient, sale: Sale) -> None:
    response = await client.post(
        f"/events/{sale.event_id}/holds",
        json={"tier_id": sale.tier_id, "quantity": 1},
        headers={"Idempotency-Key": new_key()},
    )
    assert response.status_code == 401


@pytest.mark.parametrize("quantity", [0, 11])
async def test_quantity_must_be_1_to_10(client: AsyncClient, sale: Sale, quantity: int) -> None:
    assert (await hold(client, sale, quantity=quantity)).status_code == 422


async def test_a_tier_from_another_event_is_404(client: AsyncClient, sale: Sale) -> None:
    response = await hold(client, sale, tier_id=sale.other_tier_id)

    assert response.status_code == 404
    assert response.json()["error"] == "tier_not_found"


async def test_events_that_are_not_on_sale_are_refused(
    client: AsyncClient, db_engine: AsyncEngine, sale: Sale
) -> None:
    draft, draft_tier = await make_event(
        db_engine, 1, EventStatus.DRAFT, SeatingType.GENERAL_ADMISSION, 5
    )
    cancelled, cancelled_tier = await make_event(
        db_engine, 1, EventStatus.CANCELLED, SeatingType.GENERAL_ADMISSION, 5
    )
    reserved, reserved_tier = await make_event(
        db_engine, 1, EventStatus.PUBLISHED, SeatingType.RESERVED, 5
    )

    async def try_hold(event_id: int, tier_id: int) -> Response:
        return await client.post(
            f"/events/{event_id}/holds",
            json={"tier_id": tier_id, "quantity": 1},
            headers={**bearer(1), "Idempotency-Key": new_key()},
        )

    assert (await try_hold(draft, draft_tier)).status_code == 404
    assert (await try_hold(99999, sale.tier_id)).status_code == 404
    assert (await try_hold(cancelled, cancelled_tier)).json()["error"] == "event_not_on_sale"
    assert (await try_hold(reserved, reserved_tier)).json()["error"] == "seating_not_supported"


async def test_300_buyers_over_http_get_exactly_50_seats(
    client: AsyncClient, redis: Redis, sale: Sale
) -> None:
    start = asyncio.Event()

    async def buyer(user_id: int) -> Response:
        await start.wait()
        return await hold(client, sale, user_id=user_id)

    tasks = [asyncio.create_task(buyer(user_id)) for user_id in range(1, 301)]
    await asyncio.sleep(0)
    start.set()
    responses = await asyncio.gather(*tasks)

    statuses = [r.status_code for r in responses]
    assert statuses.count(201) == 50
    assert statuses.count(409) == 250
    assert {r.json()["error"] for r in responses if r.status_code == 409} == {"sold_out"}
    assert await redis.get(inventory_key(sale.event_id, sale.tier_id)) == "0"
