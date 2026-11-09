"""Rate-limit checks used by the routes: holds per user, logins per email and per IP."""

import logging

from fastapi import Depends, Request
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.api.dependencies import get_current_user, get_redis
from app.core.errors import RateLimited
from app.core.settings import get_settings
from app.core.tokens import AccessTokenClaims
from app.redis.rate_limit import RateLimiter, hashed, rate_limit_key

logger = logging.getLogger(__name__)


async def limit_holds(
    user: AccessTokenClaims = Depends(get_current_user),
    redis: Redis = Depends(get_redis),
) -> None:
    """At most `rate_limit_holds` hold requests per user per window (retries count too)."""
    settings = get_settings()
    wait = await RateLimiter(redis).retry_after_seconds(
        rate_limit_key("holds", str(user.user_id)),
        limit=settings.rate_limit_holds,
        window_seconds=settings.rate_limit_window_seconds,
    )
    if wait:
        raise RateLimited(wait)


def client_ip(request: Request) -> str:
    # Behind nginx (S8.1) this becomes nginx's address; trusting its
    # X-Forwarded-For header is set up there.
    return request.client.host if request.client else "unknown"


async def limit_login(redis: Redis, *, email: str, ip: str) -> None:
    """Slow down password guessing: per email address (any IP) and per IP (any email).

    If Redis can't be reached, the check is skipped and logged: a Redis
    outage must not lock every user out of their account.
    """
    settings = get_settings()
    limiter = RateLimiter(redis)
    try:
        waits = [
            await limiter.retry_after_seconds(
                rate_limit_key("login-email", hashed(email)),
                limit=settings.rate_limit_login_per_email,
                window_seconds=settings.rate_limit_window_seconds,
            ),
            await limiter.retry_after_seconds(
                rate_limit_key("login-ip", ip),
                limit=settings.rate_limit_login_per_ip,
                window_seconds=settings.rate_limit_window_seconds,
            ),
        ]
    except RedisError:
        logger.warning("login rate limit skipped: Redis unavailable")
        return
    if max(waits):
        raise RateLimited(max(waits))
