"""Rate limiting on top of rate_limit.lua: "at most N requests per window" for one caller."""

import hashlib
import math
import uuid

from redis.asyncio import Redis

from app.redis.scripts import LUA_DIR
from app.redis.timed_script import register_timed_script

RATE_LIMIT_LUA = (LUA_DIR / "rate_limit.lua").read_text()


def rate_limit_key(scope: str, who: str) -> str:
    return f"rl:{scope}:{who}"


def hashed(value: str) -> str:
    """Keys must not contain personal data such as an email address, so store a hash."""
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()[:32]


class RateLimiter:
    def __init__(self, redis: Redis) -> None:
        self._script = register_timed_script(redis, RATE_LIMIT_LUA, "rate_limit")

    async def retry_after_seconds(self, key: str, *, limit: int, window_seconds: float) -> int:
        """Count this request. 0 if allowed; otherwise how many seconds to wait (at least 1)."""
        retry_ms = int(
            await self._script(
                keys=[key], args=[int(window_seconds * 1000), limit, uuid.uuid4().hex]
            )
        )
        return 0 if retry_ms == 0 else max(1, math.ceil(retry_ms / 1000))
