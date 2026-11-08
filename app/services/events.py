"""Admin event management: create an event with its tiers, update it, delete a draft.

Who may call these is checked in the API layer (require_admin); this module
enforces the business rules, such as which status changes are allowed.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import EventNotDeletable, EventNotFound, InvalidEventStatusChange
from app.db.models import Event, EventStatus, SeatingType, Tier

# Events only move forward. CANCELLED is final, and nothing returns to DRAFT.
ALLOWED_STATUS_CHANGES: dict[EventStatus, set[EventStatus]] = {
    EventStatus.DRAFT: {EventStatus.PUBLISHED, EventStatus.CANCELLED},
    EventStatus.PUBLISHED: {EventStatus.CANCELLED},
    EventStatus.CANCELLED: set(),
}


@dataclass(frozen=True)
class TierSpec:
    name: str
    price_cents: int
    capacity: int


@dataclass(frozen=True)
class EventChanges:
    """Fields to change. None means "leave as it is"."""

    name: str | None = None
    description: str | None = None
    starts_at: datetime | None = None
    venue: str | None = None
    city: str | None = None
    status: EventStatus | None = None


@dataclass(frozen=True)
class EventWithTiers:
    event: Event
    tiers: list[Tier]


async def create_event(
    session: AsyncSession,
    *,
    created_by: int,
    name: str,
    description: str | None,
    starts_at: datetime,
    venue: str,
    city: str,
    seating: SeatingType,
    tiers: list[TierSpec],
) -> EventWithTiers:
    """Create a DRAFT event and its tiers in one transaction (all saved, or none)."""
    event = Event(
        name=name,
        description=description,
        starts_at=starts_at,
        venue=venue,
        city=city,
        seating=seating,
        status=EventStatus.DRAFT,
        created_by=created_by,
    )
    session.add(event)
    # flush sends the INSERT so Postgres assigns event.id, without committing yet.
    await session.flush()
    tier_rows = [
        Tier(event_id=event.id, name=t.name, price_cents=t.price_cents, capacity=t.capacity)
        for t in tiers
    ]
    session.add_all(tier_rows)
    await session.commit()
    return EventWithTiers(event=event, tiers=tier_rows)


async def update_event(
    session: AsyncSession, event_id: int, changes: EventChanges
) -> EventWithTiers:
    """Apply changes to an event. Raises EventNotFound or InvalidEventStatusChange."""
    event = await _get_locked(session, event_id)

    if changes.status is not None and changes.status != event.status:
        if changes.status not in ALLOWED_STATUS_CHANGES[event.status]:
            raise InvalidEventStatusChange()
        event.status = changes.status
    if changes.name is not None:
        event.name = changes.name
    if changes.description is not None:
        event.description = changes.description
    if changes.starts_at is not None:
        event.starts_at = changes.starts_at
    if changes.venue is not None:
        event.venue = changes.venue
    if changes.city is not None:
        event.city = changes.city

    await session.commit()
    return EventWithTiers(event=event, tiers=await _tiers_of(session, event.id))


async def delete_event(session: AsyncSession, event_id: int) -> None:
    """Delete a DRAFT event and its tiers. Published events must be cancelled instead."""
    event = await _get_locked(session, event_id)
    if event.status != EventStatus.DRAFT:
        raise EventNotDeletable()
    # Tiers first: the foreign key refuses to leave tiers pointing at nothing.
    await session.execute(delete(Tier).where(Tier.event_id == event.id))
    await session.delete(event)
    await session.commit()


async def _get_locked(session: AsyncSession, event_id: int) -> Event:
    # FOR UPDATE locks the row until commit, so two admins changing the same
    # event at once take turns instead of both passing the status check.
    event = await session.get(Event, event_id, with_for_update=True)
    if event is None:
        raise EventNotFound()
    return event


async def _tiers_of(session: AsyncSession, event_id: int) -> list[Tier]:
    result = await session.scalars(select(Tier).where(Tier.event_id == event_id).order_by(Tier.id))
    return list(result)


# --- public reading (S1.7) -----------------------------------------------------

# What the public may see: published events in lists; published or cancelled
# on a detail page (so ticket holders can see a cancellation). Drafts never.
PUBLICLY_VISIBLE = (EventStatus.PUBLISHED, EventStatus.CANCELLED)


@dataclass(frozen=True)
class EventPage:
    events: list[Event]
    total: int  # how many match in all, not just on this page


def contains_pattern(text: str) -> str:
    """Turn user text into a safe "contains" pattern for ILIKE.

    In LIKE patterns, % means "anything" and _ means "any one character".
    Escaping them makes a search for "50%" look for those literal characters
    instead of matching every event.
    """
    # Escape the escape character itself first, then the two wildcards.
    escaped = (
        text.replace(LIKE_ESCAPE, LIKE_ESCAPE * 2)
        .replace("%", LIKE_ESCAPE + "%")
        .replace("_", LIKE_ESCAPE + "_")
    )
    return f"%{escaped}%"


LIKE_ESCAPE = "\\"  # a single backslash (Python needs it written twice)


async def list_upcoming_events(
    session: AsyncSession,
    *,
    query: str | None,
    city: str | None,
    limit: int,
    offset: int,
    now: datetime,
) -> EventPage:
    """Published events that haven't started, soonest first, optionally filtered."""
    conditions = [Event.status == EventStatus.PUBLISHED, Event.starts_at > now]
    if query:
        conditions.append(Event.name.ilike(contains_pattern(query), escape=LIKE_ESCAPE))
    if city:
        conditions.append(func.lower(Event.city) == city.strip().lower())

    total = await session.scalar(select(func.count()).select_from(Event).where(*conditions))
    # Order by starts_at, then id, so events starting at the same moment
    # always come in the same order and paging never skips or repeats one.
    rows = await session.scalars(
        select(Event)
        .where(*conditions)
        .order_by(Event.starts_at, Event.id)
        .limit(limit)
        .offset(offset)
    )
    return EventPage(events=list(rows), total=total or 0)


async def get_public_event(session: AsyncSession, event_id: int) -> EventWithTiers:
    """One event with its tiers. A draft is reported as not found, as if it didn't exist."""
    event = await session.get(Event, event_id)
    if event is None or event.status not in PUBLICLY_VISIBLE:
        raise EventNotFound()
    return EventWithTiers(event=event, tiers=await _tiers_of(session, event.id))
