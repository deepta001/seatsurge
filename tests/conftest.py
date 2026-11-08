"""Shared pytest setup, loaded automatically before any test file.

1. Points the app's settings at addresses where nothing listens (port 1), so
   no test can ever touch your real Postgres or Redis. This must run before
   `app.main` is imported, because settings are read at import time.
2. Provides real-database fixtures: one throwaway Postgres container per test
   run (testcontainers), built with our real Alembic migrations. Only tests
   that ask for `client` or `db_engine` start it, so unit tests stay fast and
   don't need Docker.
"""

import os

# Plain assignment (not setdefault), so values already in your shell can't
# leak real services into the tests.
os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = "postgresql+asyncpg://test:test@127.0.0.1:1/test"
os.environ["REDIS_URL"] = "redis://:test@127.0.0.1:1/0"

from collections.abc import AsyncIterator, Iterator  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine  # noqa: E402
from testcontainers.community.postgres import PostgresContainer  # noqa: E402

from app.api.dependencies import get_db_session  # noqa: E402
from app.db.session import create_session_factory  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """Start a throwaway Postgres 16 for the whole test run and migrate it to head."""
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as container:
        # 127.0.0.1, not localhost: on Windows, localhost tries IPv6 first and
        # costs ~2s per new connection (found in S0.8).
        url = container.get_connection_url().replace("@localhost:", "@127.0.0.1:")
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", url)
        # The real migrations, not create_all, so tests also prove they work.
        command.upgrade(config, "head")
        yield url


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def db_engine(postgres_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(postgres_url)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def client(db_engine: AsyncEngine) -> AsyncIterator[AsyncClient]:
    """An HTTP client wired to the test database. Tables are emptied after each test."""
    session_factory = create_session_factory(db_engine)

    async def session_for_tests() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = session_for_tests
    # ASGITransport calls the app directly in this event loop: no server, no port.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
    app.dependency_overrides.clear()

    # A clean slate, so no test depends on what another left behind.
    async with db_engine.begin() as connection:
        await connection.execute(text("TRUNCATE users, events, tiers RESTART IDENTITY CASCADE"))
