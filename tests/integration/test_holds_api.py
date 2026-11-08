"""POST /events/{id}/holds over HTTP, with a real Postgres and a real Redis."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient, Response
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.dependencies import get_redis
from app.core.tokens import create_access_token
from app.db.models import EventStatus, SeatingType, UserRole
from app.db.session import create_session_factory
from app.main import app
from app.redis.keys import hold_key, inventory_key
from app.services.auth import create_admin
from app.services.events import EventChanges, TierSpec, create_event, update_event


@dataclass
class Sale:
    event_id: int
    tier_id: int
    other_tier_id: int  # a tier that belongs to a different event


def bearer(user_id: int) -> dict[str, str]:
    # Tokens are checked without the database, so made-up user ids are fine.
    return {"Authorization": f"Bearer {create_access_token(user_id, UserRole.USER)}"}


async def make_event(
    db_engine: AsyncEngine, admin_id: int, status: EventStatus, seating: SeatingType, capacity: int
) -> tuple[int, int]:
    async with create_session_factory(db_engine)() as session:
        result = await create_event(
            session,
            created_by=admin_id,
            name=f"{status} {seating}",
            description=None,
            starts_at=datetime.now(UTC) + timedelta(days=7),
            venue="Hall",
            city="Leeds",
            seating=seating,
            tiers=[TierSpec("Floor", 5000, capacity)],
        )
        if status != EventStatus.DRAFT:
            await update_event(session, result.event.id, EventChanges(status=status))
        return result.event.id, result.tiers[0].id


@pytest.fixture
async def sale(client: AsyncClient, redis: Redis, db_engine: AsyncEngine) -> AsyncIterator[Sale]:
    """A published event with 50 Floor seats, its Redis counter set, and the app on test Redis."""
    async with create_session_factory(db_engine)() as session:
        admin = await create_admin(
            session, email="a@example.com", username="admin", password="a long password!"
        )
    event_id, tier_id = await make_event(
        db_engine, admin.id, EventStatus.PUBLISHED, SeatingType.GENERAL_ADMISSION, 50
    )
    _, other_tier_id = await make_event(
        db_engine, admin.id, EventStatus.PUBLISHED, SeatingType.GENERAL_ADMISSION, 5
    )
    # Until S2.8 rebuilds counters automatically, tests set them up directly.
    await redis.set(inventory_key(event_id, tier_id), 50)
    app.dependency_overrides[get_redis] = lambda: redis
    yield Sale(event_id, tier_id, other_tier_id)


async def hold(
    client: AsyncClient, sale: Sale, user_id: int = 1, quantity: int = 1, tier_id: int | None = None
) -> Response:
    return await client.post(
        f"/events/{sale.event_id}/holds",
        json={"tier_id": tier_id or sale.tier_id, "quantity": quantity},
        headers=bearer(user_id),
    )


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
        f"/events/{sale.event_id}/holds", json={"tier_id": sale.tier_id, "quantity": 1}
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
            headers=bearer(1),
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
