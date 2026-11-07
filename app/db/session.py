"""Creates the async SQLAlchemy engine: the app's shared pool of Postgres connections."""

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

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
    )
