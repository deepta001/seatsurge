"""Event routes. Admin-only for now: POST /events, PATCH /events/{id}, DELETE /events/{id}.

Public reading (GET /events, GET /events/{id}) comes in S1.7.
"""

from datetime import UTC, datetime
from typing import Self

from fastapi import APIRouter, Depends, status
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session, require_admin
from app.core.tokens import AccessTokenClaims
from app.db.models import EventStatus, SeatingType
from app.services.events import (
    EventChanges,
    EventWithTiers,
    TierSpec,
    create_event,
    delete_event,
    update_event,
)

router = APIRouter(prefix="/events", tags=["events"])


def must_be_in_the_future(value: datetime | None) -> datetime | None:
    if value is not None and value <= datetime.now(UTC):
        raise ValueError("must be in the future")
    return value


class TierIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    price_cents: int = Field(ge=0, le=10_000_000)  # up to 100,000.00
    capacity: int = Field(ge=1, le=100_000)


class EventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    # AwareDatetime rejects times without a time zone ("20:00" where?).
    starts_at: AwareDatetime
    venue: str = Field(min_length=1, max_length=200)
    city: str = Field(min_length=1, max_length=100)
    seating: SeatingType
    tiers: list[TierIn] = Field(min_length=1, max_length=20)

    _starts_in_future = field_validator("starts_at")(must_be_in_the_future)

    @field_validator("tiers")
    @classmethod
    def tier_names_are_unique(cls, tiers: list[TierIn]) -> list[TierIn]:
        # The DB's UNIQUE(event_id, name) would also refuse this; checking here
        # gives a clear 422 instead of a database error.
        names = [t.name.casefold() for t in tiers]
        if len(names) != len(set(names)):
            raise ValueError("tier names must be unique within an event")
        return tiers


class EventUpdate(BaseModel):
    """Only the fields you send are changed. Tiers can't be edited yet."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    starts_at: AwareDatetime | None = None
    venue: str | None = Field(default=None, min_length=1, max_length=200)
    city: str | None = Field(default=None, min_length=1, max_length=100)
    status: EventStatus | None = None

    _starts_in_future = field_validator("starts_at")(must_be_in_the_future)

    @model_validator(mode="after")
    def something_to_change(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("send at least one field to change")
        return self


class TierResponse(BaseModel):
    id: int
    name: str
    price_cents: int
    capacity: int


class EventResponse(BaseModel):
    id: int
    name: str
    description: str | None
    starts_at: datetime
    venue: str
    city: str
    seating: SeatingType
    status: EventStatus
    created_by: int
    tiers: list[TierResponse]


def to_response(result: EventWithTiers) -> EventResponse:
    """Copy fields explicitly, never the ORM object itself (CLAUDE.md section 8)."""
    event = result.event
    return EventResponse(
        id=event.id,
        name=event.name,
        description=event.description,
        starts_at=event.starts_at,
        venue=event.venue,
        city=event.city,
        seating=event.seating,
        status=event.status,
        created_by=event.created_by,
        tiers=[
            TierResponse(id=t.id, name=t.name, price_cents=t.price_cents, capacity=t.capacity)
            for t in result.tiers
        ],
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create(
    body: EventCreate,
    admin: AccessTokenClaims = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> EventResponse:
    """Create a DRAFT event with its price tiers. Admins only."""
    result = await create_event(
        session,
        created_by=admin.user_id,
        name=body.name,
        description=body.description,
        starts_at=body.starts_at,
        venue=body.venue,
        city=body.city,
        seating=body.seating,
        tiers=[TierSpec(t.name, t.price_cents, t.capacity) for t in body.tiers],
    )
    return to_response(result)


@router.patch("/{event_id}")
async def update(
    event_id: int,
    body: EventUpdate,
    _admin: AccessTokenClaims = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> EventResponse:
    """Change event details or status (DRAFT -> PUBLISHED -> CANCELLED). Admins only."""
    changes = EventChanges(
        name=body.name,
        description=body.description,
        starts_at=body.starts_at,
        venue=body.venue,
        city=body.city,
        status=body.status,
    )
    return to_response(await update_event(session, event_id, changes))


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(
    event_id: int,
    _admin: AccessTokenClaims = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """Delete a DRAFT event and its tiers. Admins only; published events can only be cancelled."""
    await delete_event(session, event_id)
