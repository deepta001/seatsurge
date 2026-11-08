"""Admin event management (POST/PATCH/DELETE /events) against a real Postgres."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import create_session_factory
from app.services.auth import create_admin

PASSWORD = "a long enough password"
NEXT_MONTH = (datetime.now(UTC) + timedelta(days=30)).isoformat()


def new_event(**overrides: Any) -> dict[str, Any]:
    event: dict[str, Any] = {
        "name": "Summer Concert",
        "description": "Outdoor show",
        "starts_at": NEXT_MONTH,
        "venue": "Park Stage",
        "city": "Leeds",
        "seating": "GENERAL_ADMISSION",
        "tiers": [
            {"name": "Floor", "price_cents": 5000, "capacity": 100},
            {"name": "Balcony", "price_cents": 3000, "capacity": 50},
        ],
    }
    event.update(overrides)
    return event


async def bearer(client: AsyncClient, email: str) -> dict[str, str]:
    login = await client.post("/auth/login", json={"email": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture
async def admin(client: AsyncClient, db_engine: AsyncEngine) -> dict[str, str]:
    async with create_session_factory(db_engine)() as session:
        await create_admin(session, email="admin@example.com", username="admin", password=PASSWORD)
    return await bearer(client, "admin@example.com")


@pytest.fixture
async def user(client: AsyncClient) -> dict[str, str]:
    await client.post(
        "/auth/register",
        json={"email": "user@example.com", "username": "user", "password": PASSWORD},
    )
    return await bearer(client, "user@example.com")


async def create(client: AsyncClient, admin: dict[str, str], **overrides: Any) -> dict[str, Any]:
    response = await client.post("/events", json=new_event(**overrides), headers=admin)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


# --- who may do what ---------------------------------------------------------


async def test_admin_creates_a_draft_event_with_its_tiers(
    client: AsyncClient, admin: dict[str, str]
) -> None:
    event = await create(client, admin)

    assert event["status"] == "DRAFT"
    assert event["created_by"] == 1
    assert [(t["name"], t["capacity"]) for t in event["tiers"]] == [("Floor", 100), ("Balcony", 50)]


async def test_a_regular_user_gets_403_on_every_admin_route(
    client: AsyncClient, admin: dict[str, str], user: dict[str, str]
) -> None:
    event_id = (await create(client, admin))["id"]

    responses = [
        await client.post("/events", json=new_event(), headers=user),
        await client.patch(f"/events/{event_id}", json={"name": "Hacked"}, headers=user),
        await client.delete(f"/events/{event_id}", headers=user),
    ]

    assert [r.status_code for r in responses] == [403, 403, 403]
    assert responses[0].json()["error"] == "forbidden"


async def test_no_token_gets_401(client: AsyncClient) -> None:
    assert (await client.post("/events", json=new_event())).status_code == 401


# --- validation ---------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"tiers": [{"name": "Floor", "price_cents": 1, "capacity": 1}] * 2},  # duplicate names
        {"tiers": [{"name": "Floor", "price_cents": 1, "capacity": 0}]},  # capacity 0
        {"tiers": []},  # no tiers
        {"starts_at": (datetime.now(UTC) - timedelta(days=1)).isoformat()},  # in the past
        {"starts_at": "2099-01-01T20:00:00"},  # no time zone
        {"seating": "STANDING"},  # not a seating type
        {"status": "PUBLISHED"},  # status can't be set at creation
    ],
)
async def test_bad_event_data_gets_422_and_nothing_is_saved(
    client: AsyncClient, admin: dict[str, str], db_engine: AsyncEngine, overrides: dict[str, Any]
) -> None:
    response = await client.post("/events", json=new_event(**overrides), headers=admin)

    assert response.status_code == 422
    async with db_engine.connect() as connection:
        assert await connection.scalar(text("SELECT count(*) FROM events")) == 0


async def test_an_empty_patch_is_rejected(client: AsyncClient, admin: dict[str, str]) -> None:
    event_id = (await create(client, admin))["id"]

    assert (await client.patch(f"/events/{event_id}", json={}, headers=admin)).status_code == 422


# --- status rules -------------------------------------------------------------


async def test_status_moves_forward_draft_published_cancelled(
    client: AsyncClient, admin: dict[str, str]
) -> None:
    event_id = (await create(client, admin))["id"]
    url = f"/events/{event_id}"

    published = await client.patch(url, json={"status": "PUBLISHED"}, headers=admin)
    cancelled = await client.patch(url, json={"status": "CANCELLED"}, headers=admin)
    back_again = await client.patch(url, json={"status": "PUBLISHED"}, headers=admin)
    to_draft = await client.patch(url, json={"status": "DRAFT"}, headers=admin)

    assert published.json()["status"] == "PUBLISHED"
    assert cancelled.json()["status"] == "CANCELLED"
    assert back_again.status_code == 409
    assert back_again.json()["error"] == "invalid_status_change"
    assert to_draft.status_code == 409


async def test_patch_changes_only_the_fields_sent(
    client: AsyncClient, admin: dict[str, str]
) -> None:
    event_id = (await create(client, admin))["id"]

    updated = await client.patch(f"/events/{event_id}", json={"city": "York"}, headers=admin)

    assert updated.json()["city"] == "York"
    assert updated.json()["name"] == "Summer Concert"
    assert len(updated.json()["tiers"]) == 2


async def test_unknown_event_gets_404(client: AsyncClient, admin: dict[str, str]) -> None:
    response = await client.patch("/events/999", json={"name": "x"}, headers=admin)

    assert response.status_code == 404
    assert response.json()["error"] == "event_not_found"


# --- deleting -----------------------------------------------------------------


async def test_deleting_a_draft_removes_it_and_its_tiers(
    client: AsyncClient, admin: dict[str, str], db_engine: AsyncEngine
) -> None:
    event_id = (await create(client, admin))["id"]

    assert (await client.delete(f"/events/{event_id}", headers=admin)).status_code == 204
    async with db_engine.connect() as connection:
        assert await connection.scalar(text("SELECT count(*) FROM events")) == 0
        assert await connection.scalar(text("SELECT count(*) FROM tiers")) == 0


async def test_a_published_event_cannot_be_deleted_only_cancelled(
    client: AsyncClient, admin: dict[str, str]
) -> None:
    event_id = (await create(client, admin))["id"]
    await client.patch(f"/events/{event_id}", json={"status": "PUBLISHED"}, headers=admin)

    response = await client.delete(f"/events/{event_id}", headers=admin)

    assert response.status_code == 409
    assert response.json()["error"] == "event_not_deletable"
