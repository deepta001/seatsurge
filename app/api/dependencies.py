"""FastAPI dependencies: small functions that hand shared objects to route functions.

Routes ask for what they need (`engine: AsyncEngine = Depends(get_db_engine)`),
and tests can swap these out with `app.dependency_overrides`.
"""

from fastapi import Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine


def get_db_engine(request: Request) -> AsyncEngine:
    """The Postgres engine created at startup by `lifespan` in app/main.py."""
    engine: AsyncEngine = request.app.state.db_engine
    return engine


def get_redis(request: Request) -> Redis:
    """The Redis client created at startup by `lifespan` in app/main.py."""
    redis: Redis = request.app.state.redis
    return redis
