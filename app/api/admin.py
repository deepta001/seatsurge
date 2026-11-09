"""Admin operations routes: POST /admin/events/{id}/reconcile."""

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session, get_redis, require_admin
from app.core.tokens import AccessTokenClaims
from app.services.reconcile import reconcile_event

router = APIRouter(prefix="/admin", tags=["admin"])


class TierCounter(BaseModel):
    tier_id: int
    before: int | None  # null: the counter was missing
    after: int


class ReconcileResult(BaseModel):
    event_id: int
    tiers: list[TierCounter]
    # PENDING orders whose message was published again (e.g. lost in a Redis flush).
    requeued_orders: int


@router.post("/events/{event_id}/reconcile")
async def reconcile(
    event_id: int = Path(ge=1),
    _admin: AccessTokenClaims = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis),
) -> ReconcileResult:
    """Recompute this event's Redis seat counters from Postgres and live holds.

    Safe during a sale: new holds pause for the moment each counter is
    rebuilt. Shows each counter before and after, so drift is visible. Also
    re-sends PENDING orders' messages, in case they were lost.
    """
    result = await reconcile_event(session, redis, event_id)
    return ReconcileResult(
        event_id=event_id,
        tiers=[
            TierCounter(tier_id=t.tier_id, before=t.before, after=t.after) for t in result.tiers
        ],
        requeued_orders=result.requeued_orders,
    )
