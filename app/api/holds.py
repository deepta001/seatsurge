"""POST /events/{event_id}/holds: reserve seats for a few minutes, ready to confirm.

Requires an Idempotency-Key header, so a retried request (say, after a dropped
connection) returns the first answer instead of creating a second hold.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Header, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db_session, get_redis
from app.core.errors import DomainError
from app.core.tokens import AccessTokenClaims
from app.services import idempotency
from app.services.holds import create_hold
from app.services.idempotency import StoredResponse

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


@router.post(
    "/events/{event_id}/holds",
    status_code=status.HTTP_201_CREATED,
    response_model=HoldResponse,
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
) -> HoldResponse | JSONResponse:
    """Hold seats in one tier for 5 minutes. 409 sold_out if there aren't enough."""
    fingerprint = idempotency.request_fingerprint(
        f"POST /events/{event_id}/holds", body.model_dump()
    )
    stored = await idempotency.begin(redis, user.user_id, idempotency_key, fingerprint)
    if stored is not None:
        # This exact request already finished: replay its answer, do nothing new.
        return JSONResponse(
            status_code=stored.status_code,
            content=stored.body,
            headers={"Idempotent-Replayed": "true"},
        )

    try:
        hold = await create_hold(
            session,
            redis,
            user_id=user.user_id,
            event_id=event_id,
            tier_id=body.tier_id,
            quantity=body.quantity,
        )
    except DomainError as error:
        if error.status_code < 500:
            # A final answer (sold out, not found...): retries must see the same.
            await idempotency.complete(
                redis,
                user.user_id,
                idempotency_key,
                fingerprint,
                StoredResponse(error.status_code, {"error": error.code, "message": error.message}),
            )
        else:
            # Temporary (e.g. 503 inventory not ready): let a retry try again.
            await idempotency.abandon(redis, user.user_id, idempotency_key)
        raise
    except Exception:
        await idempotency.abandon(redis, user.user_id, idempotency_key)
        raise

    response = HoldResponse(
        hold_id=hold.hold_id,
        event_id=hold.event_id,
        tier_id=hold.tier_id,
        quantity=hold.quantity,
        expires_at=hold.expires_at,
    )
    await idempotency.complete(
        redis,
        user.user_id,
        idempotency_key,
        fingerprint,
        StoredResponse(status.HTTP_201_CREATED, response.model_dump(mode="json")),
    )
    return response
