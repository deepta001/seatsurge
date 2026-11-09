"""A Lua script that records how long each run takes (CLAUDE.md section 10).

Every script wrapper registers its script through `register_timed_script`
instead of `redis.register_script`, so all of them are timed the same way
without repeating the timing code in each wrapper.
"""

import time
from typing import Any

from redis.asyncio import Redis

from app.core.metrics import REDIS_SCRIPT_DURATION


class TimedScript:
    """Calls a registered script exactly like redis-py does, and times the call."""

    def __init__(self, redis: Redis, lua: str, name: str) -> None:
        self._script = redis.register_script(lua)
        self._timer = REDIS_SCRIPT_DURATION.labels(name)

    async def __call__(self, keys: list[Any], args: list[Any]) -> Any:
        started = time.perf_counter()
        try:
            return await self._script(keys=keys, args=args)
        finally:
            # Failed calls are timed too: a slow error is still a slow Redis.
            self._timer.observe(time.perf_counter() - started)


def register_timed_script(redis: Redis, lua: str, name: str) -> TimedScript:
    return TimedScript(redis, lua, name)
