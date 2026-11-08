"""Shared test setup for selling seats: an event on sale, tokens, and a hold helper.

Loaded for every test via `pytest_plugins` in tests/conftest.py.
"""

import uuid
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
from app.redis.keys import inventory_key
from app.services.auth import create_admin
from app.services.events import EventChanges, TierSpec, create_event, update_event


@dataclass
class Sale:
    event_id: int
    tier_id: int
    other_tier_id: int  # a tier that belongs to a different event
    admin_id: int


def bearer(user_id: int) -> dict[str, str]:
    # Tokens are checked without the database, so made-up user ids are fine.
    return {"Authorization": f"Bearer {create_access_token(user_id, UserRole.USER)}"}


def new_key() -> str:
    """A fresh Idempotency-Key, as a client would generate per purchase attempt."""
    return str(uuid.uuid4())


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
    yield Sale(event_id, tier_id, other_tier_id, admin.id)


async def hold(
    client: AsyncClient,
    sale: Sale,
    user_id: int = 1,
    quantity: int = 1,
    tier_id: int | None = None,
    key: str | None = None,
) -> Response:
    """POST a hold. A fresh Idempotency-Key unless `key` is given (for retry tests)."""
    return await client.post(
        f"/events/{sale.event_id}/holds",
        json={"tier_id": tier_id or sale.tier_id, "quantity": quantity},
        headers={**bearer(user_id), "Idempotency-Key": key or new_key()},
    )
