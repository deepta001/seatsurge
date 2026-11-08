"""Public event routes (no login): GET /events and GET /events/{id}.

These use their own response models, so admin-only details (such as which
admin created an event) are never exposed (CLAUDE.md section 8).
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session
from app.db.models import Event, EventStatus, SeatingType
from app.services.events import get_public_event, list_upcoming_events

router = APIRouter(prefix="/events", tags=["events"])


class EventSummary(BaseModel):
    """One row in the event list: enough to show a card, no tiers."""

    id: int
    name: str
    starts_at: datetime
    venue: str
    city: str
    seating: SeatingType


class EventList(BaseModel):
    items: list[EventSummary]
    total: int
    limit: int
    offset: int


class PublicTier(BaseModel):
    id: int
    name: str
    price_cents: int
    capacity: int


class EventDetail(BaseModel):
    id: int
    name: str
    description: str | None
    starts_at: datetime
    venue: str
    city: str
    seating: SeatingType
    status: EventStatus
    tiers: list[PublicTier]


def to_summary(event: Event) -> EventSummary:
    return EventSummary(
        id=event.id,
        name=event.name,
        starts_at=event.starts_at,
        venue=event.venue,
        city=event.city,
        seating=event.seating,
    )


@router.get("")
async def list_events(
    query: str | None = Query(default=None, max_length=100, description="Text in the event name"),
    city: str | None = Query(default=None, max_length=100),
    # A hard cap on page size, so nobody can ask for a million rows at once.
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10_000),
    session: AsyncSession = Depends(get_db_session),
) -> EventList:
    """Upcoming published events, soonest first. Anyone can call this."""
    page = await list_upcoming_events(
        session, query=query, city=city, limit=limit, offset=offset, now=datetime.now(UTC)
    )
    return EventList(
        items=[to_summary(e) for e in page.events], total=page.total, limit=limit, offset=offset
    )


@router.get("/{event_id}")
async def read_event(event_id: int, session: AsyncSession = Depends(get_db_session)) -> EventDetail:
    """One published or cancelled event with its price tiers. Drafts are 404."""
    result = await get_public_event(session, event_id)
    event = result.event
    return EventDetail(
        id=event.id,
        name=event.name,
        description=event.description,
        starts_at=event.starts_at,
        venue=event.venue,
        city=event.city,
        seating=event.seating,
        status=event.status,
        tiers=[
            PublicTier(id=t.id, name=t.name, price_cents=t.price_cents, capacity=t.capacity)
            for t in result.tiers
        ],
    )
