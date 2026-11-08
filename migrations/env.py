"""Alembic's entry point: connects to Postgres and runs migrations.

It reads DATABASE_URL from app settings (so the password stays in .env) and
compares the database with the models in app/db/models.py when autogenerating.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.settings import get_settings

# Importing the models registers every table on Base.metadata; without this,
# autogenerate would see no tables and plan to drop them all.
from app.db import models  # noqa: F401
from app.db.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The models are the "desired" schema; autogenerate diffs the real DB against this.
target_metadata = Base.metadata


def database_url() -> str:
    return get_settings().database_url.get_secret_value()


def configure_context(**options: object) -> None:
    context.configure(
        target_metadata=target_metadata,
        # Also notice changed column defaults, not just new or removed columns.
        compare_server_default=True,
        **options,  # type: ignore[arg-type]
    )


def run_migrations_offline() -> None:
    """`alembic upgrade head --sql`: print the SQL instead of running it."""
    configure_context(url=database_url(), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_with(connection: Connection) -> None:
    configure_context(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    # NullPool: a migration is a one-off job, so don't keep connections open.
    engine = create_async_engine(database_url(), poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(run_migrations_with)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
