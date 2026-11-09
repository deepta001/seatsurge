"""Shared fixtures for reserved seating: a published theatre with real seats, and helpers."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.models import EventStatus, SeatingType
from app.db.session import create_session_factory
from app.services.events import EventChanges, TierSpec, create_event, update_event
from tests.sales import Sale, bearer, new_key


@dataclass
class Venue:
    event_id: int
    floor: list[int]  # seat ids in the Floor tier (8 seats)
    balcony: list[int]  # seat ids in the Balcony tier (4 seats)


@pytest.fixture
async def venue(sale: Sale, db_engine: AsyncEngine) -> Venue:
    """A published reserved-seating event: Floor x8, Balcony x4 (the app uses the test Redis)."""
    async with create_session_factory(db_engine)() as session:
        created = await create_event(
            session,
            created_by=sale.admin_id,
            name="Theatre",
            description=None,
            starts_at=datetime.now(UTC) + timedelta(days=7),
            venue="Hall",
            city="Leeds",
            seating=SeatingType.RESERVED,
            tiers=[TierSpec("Floor", 5000, 8), TierSpec("Balcony", 3000, 4)],
        )
        await update_event(session, created.event.id, EventChanges(status=EventStatus.PUBLISHED))
    async with db_engine.connect() as conn:
        rows = (
            await conn.execute(
                text("SELECT id, tier_id FROM seats WHERE event_id = :e ORDER BY id"),
                {"e": created.event.id},
            )
        ).all()
    floor_tier = created.tiers[0].id
    return Venue(
        created.event.id,
        [r.id for r in rows if r.tier_id == floor_tier],
        [r.id for r in rows if r.tier_id != floor_tier],
    )


async def hold_seats(
    client: AsyncClient, venue: Venue, seat_ids: list[int], user_id: int = 1, key: str | None = None
) -> Response:
    return await client.post(
        f"/events/{venue.event_id}/holds",
        json={"seat_ids": seat_ids},
        headers={**bearer(user_id), "Idempotency-Key": key or new_key()},
    )


async def seat_states(client: AsyncClient, venue: Venue) -> dict[int, str]:
    seats = (await client.get(f"/events/{venue.event_id}/seats")).json()["seats"]
    return {s["seat_id"]: s["state"] for s in seats}
