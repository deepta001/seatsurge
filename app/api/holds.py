"""POST /events/{event_id}/holds: reserve seats for a few minutes, ready to confirm.

Requires an Idempotency-Key header, so a retried request (say, after a dropped
connection) returns the first answer instead of creating a second hold.
"""

from datetime import datetime
from typing import Self

from fastapi import APIRouter, Depends, Header, Path, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db_session, get_redis
from app.api.idempotent import run_idempotently
from app.api.rate_limits import limit_holds
from app.core.tokens import AccessTokenClaims
from app.services.holds import cancel_hold, create_hold, create_seat_hold

router = APIRouter(tags=["holds"])


class HoldCreate(BaseModel):
    """General admission: {tier_id, quantity}. Reserved seating: {seat_ids}. Never both."""

    model_config = ConfigDict(extra="forbid")

    tier_id: int | None = None
    # At most 10 seats per hold (CLAUDE.md section 9).
    quantity: int | None = Field(default=None, ge=1, le=10)
    seat_ids: list[int] | None = Field(default=None, min_length=1, max_length=10)

    @model_validator(mode="after")
    def one_kind_of_hold(self) -> Self:
        general = self.tier_id is not None and self.quantity is not None
        reserved = self.seat_ids is not None
        if general == reserved or (reserved and (self.tier_id or self.quantity)):
            raise ValueError("send either tier_id and quantity, or seat_ids")
        if self.seat_ids is not None and len(set(self.seat_ids)) != len(self.seat_ids):
            raise ValueError("seat_ids must not repeat")
        return self


class HoldResponse(BaseModel):
    hold_id: str
    event_id: int
    tier_id: int
    quantity: int
    expires_at: datetime
    seat_ids: list[int] = []  # empty for general admission


@router.post(
    "/events/{event_id}/holds",
    status_code=status.HTTP_201_CREATED,
    response_model=HoldResponse,
    # Checked before anything else: a flood of requests never reaches Redis's scripts.
    dependencies=[Depends(limit_holds)],
)
async def create(
    event_id: int,
    body: HoldCreate,
    # Client-generated, e.g. a UUID, reused unchanged on every retry.
    idempotency_key: str = Header(
        alias="Idempotency-Key", min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$"
    ),
    user: AccessTokenClaims = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis),
) -> JSONResponse:
    """Hold seats for 5 minutes: a number in one tier, or (reserved seating) specific seats.

    409 sold_out if a tier hasn't enough left; 409 seat_taken if any chosen
    seat is held or sold (then none are held).
    """

    async def work() -> HoldResponse:
        if body.seat_ids is not None:
            hold = await create_seat_hold(
                session, redis, user_id=user.user_id, event_id=event_id, seat_ids=body.seat_ids
            )
        else:
            assert body.tier_id is not None and body.quantity is not None  # checked above
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
            seat_ids=list(hold.seat_ids),
        )

    return await run_idempotently(
        redis,
        user_id=user.user_id,
        key=idempotency_key,
        route=f"POST /events/{event_id}/holds",
        body=body.model_dump(),
        success_status=status.HTTP_201_CREATED,
        work=work,
    )


@router.delete("/holds/{hold_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(
    hold_id: str = Path(max_length=64),
    user: AccessTokenClaims = Depends(get_current_user),
    redis: Redis = Depends(get_redis),
) -> None:
    """Give your hold's seats back. 204 even if it was already released or expired."""
    await cancel_hold(redis, user_id=user.user_id, hold_id=hold_id)
