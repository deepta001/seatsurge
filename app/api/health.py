"""Health endpoints: /health/live (is the process up?) and /health/ready (can it do real work?).

Ready means Postgres and Redis both answer. Load balancers and Docker use these
to decide whether to send traffic to this replica.
"""

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.dependencies import get_db_engine, get_redis

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/health", tags=["health"])

# A check that hangs is as bad as one that fails, so give up after this long.
CHECK_TIMEOUT_SECONDS = 2.0

CheckResult = Literal["ok", "unavailable"]


class LiveResponse(BaseModel):
    status: Literal["ok"]


class ReadyResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, CheckResult]


async def postgres_is_up(engine: AsyncEngine) -> bool:
    """Run `SELECT 1` on Postgres. True if it answered in time."""
    try:
        async with asyncio.timeout(CHECK_TIMEOUT_SECONDS):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        return True
    # Any failure at all (refused, wrong password, timeout) means "not ready";
    # the details go to the log, never to the client (CLAUDE.md rule 10).
    except Exception:
        logger.warning("readiness: postgres check failed", exc_info=True)
        return False


async def redis_is_up(redis: Redis) -> bool:
    """Send PING to Redis. True if it answered in time."""
    try:
        async with asyncio.timeout(CHECK_TIMEOUT_SECONDS):
            await redis.ping()
        return True
    except Exception:
        logger.warning("readiness: redis check failed", exc_info=True)
        return False


@router.get("/live")
async def live() -> LiveResponse:
    """Liveness: answers as long as the process is running. Touches nothing else."""
    return LiveResponse(status="ok")


@router.get("/ready")
async def ready(
    response: Response,
    engine: AsyncEngine = Depends(get_db_engine),
    redis: Redis = Depends(get_redis),
) -> ReadyResponse:
    """Readiness: 200 if Postgres and Redis both answer, otherwise 503."""
    # Run both checks at the same time, so the worst case is one timeout, not two.
    postgres_ok, redis_ok = await asyncio.gather(postgres_is_up(engine), redis_is_up(redis))
    checks: dict[str, CheckResult] = {
        "postgres": "ok" if postgres_ok else "unavailable",
        "redis": "ok" if redis_ok else "unavailable",
    }
    if postgres_ok and redis_ok:
        return ReadyResponse(status="ready", checks=checks)
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadyResponse(status="not_ready", checks=checks)
