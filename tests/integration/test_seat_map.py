"""Reserved seating (S6.1): seats come with the event; GET /events/{id}/seats shows states."""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.tokens import create_access_token
from app.db.models import UserRole
from app.redis.keys import seat_key
from tests.integration.test_events_admin import new_event
from tests.sales import Sale


@pytest.fixture
def admin(sale: Sale) -> dict[str, str]:
    """The `sale` fixture's admin (that fixture also points the app at the test Redis)."""
    return {"Authorization": f"Bearer {create_access_token(sale.admin_id, UserRole.ADMIN)}"}


async def create(client: AsyncClient, admin: dict[str, str], **overrides: Any) -> dict[str, Any]:
    response = await client.post("/events", json=new_event(**overrides), headers=admin)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def seat_rows(db_engine: AsyncEngine, event_id: int) -> list[Any]:
    async with db_engine.connect() as conn:
        result = await conn.execute(
            text("SELECT id, tier_id, label FROM seats WHERE event_id = :e ORDER BY id"),
            {"e": event_id},
        )
        return list(result.mappings())


async def reserved_event(
    client: AsyncClient,
    admin: dict[str, str],
    *,
    publish: bool = True,
) -> dict[str, Any]:
    event = await create(
        client,
        admin,
        seating="RESERVED",
        tiers=[
            {"name": "Floor", "price_cents": 5000, "capacity": 4},
            {"name": "Balcony", "price_cents": 3000, "capacity": 2},
        ],
    )
    if publish:
        response = await client.patch(
            f"/events/{event['id']}", json={"status": "PUBLISHED"}, headers=admin
        )
        assert response.status_code == 200
    return event


async def test_a_reserved_event_gets_one_labelled_seat_per_unit_of_capacity(
    client: AsyncClient,
    admin: dict[str, str],
    db_engine: AsyncEngine,
) -> None:
    event = await reserved_event(client, admin)
    floor, balcony = (t["id"] for t in event["tiers"])

    seats = await seat_rows(db_engine, event["id"])

    assert [(s["tier_id"], s["label"]) for s in seats] == [
        (floor, "Floor-1"),
        (floor, "Floor-2"),
        (floor, "Floor-3"),
        (floor, "Floor-4"),
        (balcony, "Balcony-1"),
        (balcony, "Balcony-2"),
    ]


async def test_a_general_admission_event_has_no_seats_and_no_seat_map(
    client: AsyncClient,
    admin: dict[str, str],
    db_engine: AsyncEngine,
) -> None:
    event = await create(client, admin)
    await client.patch(f"/events/{event['id']}", json={"status": "PUBLISHED"}, headers=admin)

    assert await seat_rows(db_engine, event["id"]) == []
    response = await client.get(f"/events/{event['id']}/seats")
    assert response.status_code == 422
    assert response.json()["error"] == "no_seat_map"


async def test_a_reserved_event_is_capped_at_5000_seats(
    client: AsyncClient,
    admin: dict[str, str],
) -> None:
    too_big = new_event(
        seating="RESERVED",
        tiers=[
            {"name": "Floor", "price_cents": 1, "capacity": 4000},
            {"name": "Balcony", "price_cents": 1, "capacity": 1001},
        ],
    )
    assert (await client.post("/events", json=too_big, headers=admin)).status_code == 422
    # The same sizes are fine for general admission (no seat rows).
    too_big["seating"] = "GENERAL_ADMISSION"
    assert (await client.post("/events", json=too_big, headers=admin)).status_code == 201


async def test_drafts_and_unknown_events_have_no_public_seat_map(
    client: AsyncClient,
    admin: dict[str, str],
) -> None:
    draft = await reserved_event(client, admin, publish=False)

    assert (await client.get(f"/events/{draft['id']}/seats")).status_code == 404
    assert (await client.get("/events/999999/seats")).status_code == 404


async def test_seat_states_come_from_tickets_and_live_holds(
    client: AsyncClient,
    admin: dict[str, str],
    db_engine: AsyncEngine,
    redis: Redis,
) -> None:
    event = await reserved_event(client, admin)
    event_id = event["id"]
    s1, s2, s3, s4, *_ = [s["id"] for s in await seat_rows(db_engine, event_id)]
    floor = event["tiers"][0]["id"]
    # Seat 2 is held (a hold key in Redis), seat 3 is sold (an ISSUED ticket),
    # seat 4 was sold then cancelled (its ticket no longer counts).
    await redis.set(seat_key(event_id, s2), "some-hold-id")
    async with db_engine.begin() as conn:
        user = await conn.scalar(
            text(
                "INSERT INTO users (email, username, password_hash) "
                "VALUES ('seatbuyer@example.com', 'seatbuyer', 'x') RETURNING id"
            )
        )
        order_id = uuid.uuid4()
        await conn.execute(
            text(
                "INSERT INTO orders (id, user_id, event_id, tier_id, quantity, hold_id, "
                "idempotency_key, total_cents, status) "
                "VALUES (:o, :u, :e, :t, 2, 'h', 'k', 0, 'CONFIRMED')"
            ),
            {"o": order_id, "u": user, "e": event_id, "t": floor},
        )
        for number, seat, status in ((1, s3, "ISSUED"), (2, s4, "CANCELLED")):
            await conn.execute(
                text(
                    "INSERT INTO tickets (order_id, event_id, tier_id, seat_id, ticket_number, "
                    "status) VALUES (:o, :e, :t, :s, :n, :st)"
                ),
                {"o": order_id, "e": event_id, "t": floor, "s": seat, "n": number, "st": status},
            )

    compact = (await client.get(f"/events/{event_id}/seats")).json()

    assert compact["event_id"] == event_id
    assert compact["seats"][:4] == [
        {"seat_id": s1, "state": "AVAILABLE"},
        {"seat_id": s2, "state": "HELD"},
        {"seat_id": s3, "state": "SOLD"},
        {"seat_id": s4, "state": "AVAILABLE"},
    ]
    assert len(compact["seats"]) == 6

    with_layout = (await client.get(f"/events/{event_id}/seats?layout=true")).json()
    assert with_layout["seats"][1] == {
        "seat_id": s2,
        "state": "HELD",
        "tier_id": floor,
        "label": "Floor-2",
    }


async def test_deleting_a_draft_reserved_event_deletes_its_seats(
    client: AsyncClient,
    admin: dict[str, str],
    db_engine: AsyncEngine,
) -> None:
    draft = await reserved_event(client, admin, publish=False)

    assert (await client.delete(f"/events/{draft['id']}", headers=admin)).status_code == 204
    assert await seat_rows(db_engine, draft["id"]) == []
