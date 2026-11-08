"""FastAPI dependencies: small functions that hand shared objects to route functions.

Routes ask for what they need (`engine: AsyncEngine = Depends(get_db_engine)`),
and tests can swap these out with `app.dependency_overrides`.
"""

from collections.abc import AsyncIterator

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.errors import NotAuthenticated
from app.core.tokens import AccessTokenClaims, decode_access_token

# Reads "Authorization: Bearer <token>". auto_error=False lets us raise our own
# typed error, and it also adds the "Authorize" button to /docs.
bearer_scheme = HTTPBearer(auto_error=False)


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


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> AccessTokenClaims:
    """The caller's id and role, taken from their access token.

    This deliberately does NOT query the database (CLAUDE.md section 9): the
    signature already proves the token is genuine, which keeps every
    authenticated request fast. The trade-off: if a user is deleted or demoted,
    their existing token still works until it expires (at most 15 minutes).
    """
    if credentials is None:
        raise NotAuthenticated()
    return decode_access_token(credentials.credentials)
