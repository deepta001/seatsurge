"""Shows why a database unique constraint is the last line of defence against double-selling.

20 concurrent "issuers" each pick the next ticket number the naive way
(read the highest number, add 1, insert). Without a unique index, several
pick the same number: two people hold "ticket 7". With the index, Postgres
rejects every duplicate. The demo uses its own scratch table
`demo_s4_5_tickets` and drops it at the end. Run from the project root:

    uv run python -m learning.examples.s4_5.unique_constraint_demo
"""

import asyncio

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import create_db_engine

TABLE = "demo_s4_5_tickets"
ISSUERS = 20


async def naive_issue(engine: AsyncEngine, start: asyncio.Event) -> bool:
    """Read max + 1, then insert. Returns False if the database refused it."""
    await start.wait()
    try:
        async with engine.begin() as conn:
            highest = await conn.scalar(
                text(f"SELECT coalesce(max(ticket_number), 0) FROM {TABLE}")
            )
            await asyncio.sleep(0.01)  # a little work in between, as real code has
            await conn.execute(
                text(f"INSERT INTO {TABLE} (ticket_number) VALUES (:n)"), {"n": highest + 1}
            )
        return True
    except IntegrityError:
        return False


async def run_round(engine: AsyncEngine, label: str) -> None:
    start = asyncio.Event()
    tasks = [asyncio.create_task(naive_issue(engine, start)) for _ in range(ISSUERS)]
    start.set()
    accepted = sum(await asyncio.gather(*tasks))
    async with engine.connect() as conn:
        numbers = list(await conn.scalars(text(f"SELECT ticket_number FROM {TABLE} ORDER BY 1")))
    duplicates = len(numbers) - len(set(numbers))
    print(
        f"{label}: {ISSUERS} issuers, {accepted} inserts accepted, "
        f"{len(set(numbers))} distinct numbers, {duplicates} DUPLICATE ticket(s)"
    )


async def main() -> None:
    engine = create_db_engine()
    try:
        async with engine.begin() as conn:
            await conn.execute(text(f"CREATE TABLE {TABLE} (ticket_number int NOT NULL)"))
        await run_round(engine, "WITHOUT a unique index")

        async with engine.begin() as conn:
            await conn.execute(text(f"TRUNCATE {TABLE}"))
            await conn.execute(text(f"CREATE UNIQUE INDEX {TABLE}_uq ON {TABLE} (ticket_number)"))
        await run_round(engine, "WITH a unique index   ")
        print("The real tickets table has this index (uq_tickets_issued_number), and the real")
        print("worker doesn't guess numbers at all: one UPDATE ... RETURNING hands them out.")
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))
        print(f"dropped {TABLE}")
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
