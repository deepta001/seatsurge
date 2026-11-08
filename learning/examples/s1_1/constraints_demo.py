"""Shows Postgres enforcing the rules in app/db/models.py, then undoes everything.

All work happens in ONE transaction that is rolled back at the end, inside a
throwaway schema, so your real database is untouched. (Postgres can even undo
CREATE TABLE.) Run from the project root with Docker up:

    uv run python -m learning.examples.s1_1.constraints_demo
"""

import asyncio

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.models import Base
from app.db.session import create_db_engine


async def try_statement(connection: AsyncConnection, label: str, sql: str) -> None:
    """Run one statement in a savepoint, so a rejected one doesn't spoil the rest."""
    try:
        async with connection.begin_nested():
            await connection.execute(text(sql))
        print(f"ALLOWED   {label}")
    except IntegrityError as error:
        # The underlying asyncpg error knows which named constraint fired.
        constraint = getattr(error.orig.__cause__, "constraint_name", "?")
        print(f"REJECTED  {label}  ->  {constraint}")


async def main() -> None:
    engine = create_db_engine()
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(text("CREATE SCHEMA demo_s1_1"))
            await connection.execute(text("SET LOCAL search_path TO demo_s1_1"))
            await connection.run_sync(Base.metadata.create_all)

            # Let Postgres assign every id. Typing id = 1 by hand would leave its
            # id counter behind, so the NEXT insert would also get id 1 and hit
            # the primary key before the rule we want to show (a real mistake
            # made while writing this demo). Fresh tables start at 1 anyway.
            await connection.execute(
                text(
                    "INSERT INTO users (email, username, password_hash) "
                    "VALUES ('asha@example.com', 'asha', 'not-a-real-hash')"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO events (name, starts_at, venue, city, seating, created_by) "
                    "VALUES ('Concert', now(), 'Hall', 'Leeds', 'GENERAL_ADMISSION', 1)"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO tiers (event_id, name, price_cents, capacity) "
                    "VALUES (1, 'Floor', 5000, 2)"
                )
            )
            print("Set up: 1 user, 1 event, tier 'Floor' with capacity 2\n")

            sell = "UPDATE tiers SET sold = sold + {n} WHERE id = 1"
            await try_statement(connection, "sell 2 of 2 seats", sell.format(n=2))
            await try_statement(connection, "sell 1 more (would be 3 of 2)", sell.format(n=1))
            await try_statement(
                connection,
                "tier with capacity 0",
                "INSERT INTO tiers (event_id, name, price_cents, capacity) "
                "VALUES (1, 'Empty', 100, 0)",
            )
            await try_statement(
                connection,
                "second 'Floor' tier for the same event",
                "INSERT INTO tiers (event_id, name, price_cents, capacity) "
                "VALUES (1, 'Floor', 100, 5)",
            )
            await try_statement(
                connection,
                "another user called 'asha'",
                "INSERT INTO users (email, username, password_hash) "
                "VALUES ('other@example.com', 'asha', 'x')",
            )
            await try_statement(
                connection,
                "user with role SUPERADMIN",
                "INSERT INTO users (email, username, password_hash, role) "
                "VALUES ('b@example.com', 'bo', 'x', 'SUPERADMIN')",
            )
            await try_statement(
                connection,
                "event created by user 999 (doesn't exist)",
                "INSERT INTO events (name, starts_at, venue, city, seating, created_by) "
                "VALUES ('Ghost', now(), 'Hall', 'Leeds', 'RESERVED', 999)",
            )
            await try_statement(
                connection,
                "delete the user who created the event",
                "DELETE FROM users WHERE id = 1",
            )

            await transaction.rollback()
            print("\nRolled back: the demo schema and everything in it is gone.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
