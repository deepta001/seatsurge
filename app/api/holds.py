"""POST /events/{event_id}/holds: reserve seats for a few minutes, ready to confirm.

Idempotency-Key handling arrives in S2.5, and stricter request limits in S2.6.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db_session, get_redis
from app.core.tokens import AccessTokenClaims
from app.services.holds import create_hold

router = APIRouter(tags=["holds"])


class HoldCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tier_id: int
    # At most 10 seats per hold (CLAUDE.md section 9).
    quantity: int = Field(ge=1, le=10)


class HoldResponse(BaseModel):
    hold_id: str
    event_id: int
    tier_id: int
    quantity: int
    expires_at: datetime


@router.post("/events/{event_id}/holds", status_code=status.HTTP_201_CREATED)
async def create(
    event_id: int,
    body: HoldCreate,
    user: AccessTokenClaims = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis),
) -> HoldResponse:
    """Hold seats in one tier for 5 minutes. 409 sold_out if there aren't enough."""
    hold = await create_hold(
        session,
        redis,
        user_id=user.user_id,
        event_id=event_id,
        tier_id=body.tier_id,
        quantity=body.quantity,
    )
    return HoldResponse(
        hold_id=hold.hold_id,
        event_id=hold.event_id,
        tier_id=hold.tier_id,
        quantity=hold.quantity,
        expires_at=hold.expires_at,
    )
