"""Creates the async SQLAlchemy engine (the pool of Postgres connections) and session factory."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.settings import get_settings


def create_db_engine() -> AsyncEngine:
    """Build an engine from DATABASE_URL. Create it once per process and reuse it."""
    settings = get_settings()
    return create_async_engine(
        # The only place the real password is unwrapped from SecretStr.
        settings.database_url.get_secret_value(),
        # Checks a pooled connection still works before handing it out, so a
        # Postgres restart doesn't cause errors on the next request.
        pool_pre_ping=True,
        # Explicit, because the total across all replicas must fit Postgres's
        # connection limit (see Settings.db_pool_size).
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """A factory that makes one short-lived session (unit of work) per request."""
    # expire_on_commit=False: after commit, objects keep their loaded values,
    # so a route can still read user.id without another trip to the database.
    return async_sessionmaker(engine, expire_on_commit=False)
