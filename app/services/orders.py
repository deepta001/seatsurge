"""Confirming a hold: turn "seats reserved for you" into a PENDING order (CLAUDE.md section 7.2).

  1. consume_hold.lua: HELD -> CONFIRMING; returns the hold's own event, tier, qty.
  2. Price from Postgres (tier price x the hold's qty) and the purchase cap.
  3. Charge the payment token (mock provider).
  4. ONE transaction: the order (PENDING) + an outbox row "issue these tickets".
If anything after step 1 fails, the hold goes back to HELD (and a payment
already taken is refunded), so the user keeps their seats until the hold expires.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    ConfirmInProgress,
    HoldExpired,
    HoldNotFound,
    IdempotencyKeyReused,
    PurchaseLimitExceeded,
)
from app.core.settings import get_settings
from app.db.models import Tier, User
from app.db.order_models import Order, OrderStatus
from app.db.outbox_models import OutboxEvent
from app.redis.confirm_scripts import (
    ConsumedHold,
    ConsumeHoldScript,
    ConsumeOutcome,
    RevertHoldScript,
)
from app.services.auth import violated_constraint
from app.services.payments import MockPaymentProvider

ORDER_PLACED = "order.placed"


@dataclass(frozen=True)
class PlacedOrder:
    order_id: uuid.UUID
    status: OrderStatus


async def confirm_hold(
    session: AsyncSession,
    redis: Redis,
    payments: MockPaymentProvider,
    *,
    user_id: int,
    hold_id: str,
    payment_token: str,
    idempotency_key: str,
    now: datetime | None = None,
) -> PlacedOrder:
    """Confirm the caller's hold and return the PENDING order, or raise a typed error."""
    now = now or datetime.now(UTC)
    consumed = await ConsumeHoldScript(redis)(
        hold_id,
        user_id=user_id,
        now_ms=int(now.timestamp() * 1000),
        grace_ms=get_settings().confirm_grace_seconds * 1000,
    )

    # NOT_OWNER looks exactly like NOT_FOUND: hold ids can't be probed (rule 1).
    if consumed.outcome in (ConsumeOutcome.NOT_FOUND, ConsumeOutcome.NOT_OWNER):
        raise HoldNotFound()
    if consumed.outcome == ConsumeOutcome.EXPIRED:
        raise HoldExpired()
    if consumed.outcome == ConsumeOutcome.ALREADY_CONFIRMING:
        # A confirm already ran (maybe a retry with a new key): hand back its order.
        existing = await session.scalar(
            select(Order).where(Order.hold_id == hold_id, Order.user_id == user_id)
        )
        if existing is None:
            raise ConfirmInProgress()  # the other confirm hasn't committed yet
        return PlacedOrder(existing.id, existing.status)

    try:
        return await _charge_and_record(
            session, payments, consumed, user_id, hold_id, payment_token, idempotency_key
        )
    except Exception:
        # Payment declined, limit reached, database error...: give the hold back.
        await RevertHoldScript(redis)(hold_id)
        raise


async def _charge_and_record(
    session: AsyncSession,
    payments: MockPaymentProvider,
    hold: ConsumedHold,
    user_id: int,
    hold_id: str,
    payment_token: str,
    idempotency_key: str,
) -> PlacedOrder:
    tier = await session.get(Tier, hold.tier_id)
    if tier is None or tier.event_id != hold.event_id:
        raise RuntimeError(f"hold {hold_id} points at a missing tier")  # never user input
    # Price from the database, quantity from the hold: nothing from the client.
    total_cents = tier.price_cents * hold.quantity

    # Cheap early check, so a user over the limit isn't charged at all.
    await _check_purchase_cap(session, user_id, hold.event_id, hold.quantity)
    await session.rollback()  # end the read-only transaction before the slow payment call

    # The charge key is tied to the hold, so a retried confirm never charges twice.
    charge = await payments.charge(
        token=payment_token, amount_cents=total_cents, idempotency_key=f"hold:{hold_id}"
    )
    try:
        # Lock this user's row: two confirms by the same user now take turns,
        # so they can't both pass the cap check (check-then-insert race).
        await session.execute(select(User.id).where(User.id == user_id).with_for_update())
        await _check_purchase_cap(session, user_id, hold.event_id, hold.quantity)
        order = Order(
            user_id=user_id,
            event_id=hold.event_id,
            tier_id=hold.tier_id,
            quantity=hold.quantity,
            hold_id=hold_id,
            idempotency_key=idempotency_key,
            status=OrderStatus.PENDING,
            total_cents=total_cents,
        )
        session.add(order)
        await session.flush()  # assigns order.id inside the transaction
        session.add(
            OutboxEvent(
                type=ORDER_PLACED,
                aggregate_id=str(order.id),
                payload={
                    "order_id": str(order.id),
                    "hold_id": hold_id,
                    "user_id": user_id,
                    "event_id": hold.event_id,
                    "tier_id": hold.tier_id,
                    "quantity": hold.quantity,
                    "total_cents": total_cents,
                },
            )
        )
        await session.commit()  # the order and its outbox row: both or neither
    except Exception as error:
        await session.rollback()
        await payments.refund(charge.charge_id)
        if isinstance(error, IntegrityError) and (
            violated_constraint(error) == "uq_orders_user_id_idempotency_key"
        ):
            raise IdempotencyKeyReused() from error
        raise
    return PlacedOrder(order.id, OrderStatus.PENDING)


async def _check_purchase_cap(
    session: AsyncSession, user_id: int, event_id: int, quantity: int
) -> None:
    """Raise PurchaseLimitExceeded if this order would take the user over the cap."""
    already = await session.scalar(
        select(func.coalesce(func.sum(Order.quantity), 0)).where(
            Order.user_id == user_id,
            Order.event_id == event_id,
            Order.status.in_([OrderStatus.PENDING, OrderStatus.CONFIRMED]),
        )
    )
    if int(already or 0) + quantity > get_settings().purchase_user_cap:
        raise PurchaseLimitExceeded()
