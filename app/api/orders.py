"""POST /holds/{hold_id}/confirm: pay for a hold and get a PENDING order (202 Accepted).

"Accepted" because the tickets aren't issued yet: the worker does that after
reading the outbox (Phase C, M4). The client can poll the order (S4.x).
"""

import uuid

from fastapi import APIRouter, Depends, Header, Path, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db_session, get_payments, get_redis
from app.api.idempotent import run_idempotently
from app.core.tokens import AccessTokenClaims
from app.db.order_models import OrderStatus
from app.services.orders import confirm_hold
from app.services.payments import MockPaymentProvider

router = APIRouter(tags=["orders"])


class ConfirmRequest(BaseModel):
    """Only the payment token. Seats, quantity and price come from the hold (rule 1).

    extra="forbid": a client that sends {"quantity": 100} or {"seat_ids": [...]}
    gets a 422 instead of having it silently ignored (adversarial test 3).
    """

    model_config = ConfigDict(extra="forbid")

    payment_token: str = Field(min_length=1, max_length=100)


class OrderAccepted(BaseModel):
    order_id: uuid.UUID
    status: OrderStatus


@router.post(
    "/holds/{hold_id}/confirm",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=OrderAccepted,
)
async def confirm(
    body: ConfirmRequest,
    hold_id: str = Path(max_length=64),
    idempotency_key: str = Header(
        alias="Idempotency-Key", min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$"
    ),
    user: AccessTokenClaims = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis),
    payments: MockPaymentProvider = Depends(get_payments),
) -> JSONResponse:
    """Confirm your hold: charge the payment and create a PENDING order."""

    async def work() -> OrderAccepted:
        order = await confirm_hold(
            session,
            redis,
            payments,
            user_id=user.user_id,
            hold_id=hold_id,
            payment_token=body.payment_token,
            idempotency_key=idempotency_key,
        )
        return OrderAccepted(order_id=order.order_id, status=order.status)

    return await run_idempotently(
        redis,
        user_id=user.user_id,
        key=idempotency_key,
        route=f"POST /holds/{hold_id}/confirm",
        body=body.model_dump(),
        success_status=status.HTTP_202_ACCEPTED,
        work=work,
    )
