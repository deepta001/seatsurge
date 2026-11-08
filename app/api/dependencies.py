"""FastAPI dependencies: small functions that hand shared objects to route functions.

Routes ask for what they need (`engine: AsyncEngine = Depends(get_db_engine)`),
and tests can swap these out with `app.dependency_overrides`.
"""

from collections.abc import AsyncIterator

from fastapi import Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


def get_db_engine(request: Request) -> AsyncEngine:
    """The Postgres engine created at startup by `lifespan` in app/main.py."""
    engine: AsyncEngine = request.app.state.db_engine
    return engine


def get_redis(request: Request) -> Redis:
    """The Redis client created at startup by `lifespan` in app/main.py."""
    redis: Redis = request.app.state.redis
    return redis


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One database session per request, closed automatically when the request ends."""
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    # `async with` closes the session (returning its connection to the pool)
    # even if the route raised an error.
    async with session_factory() as session:
        yield session
