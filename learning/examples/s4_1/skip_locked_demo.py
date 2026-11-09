"""Shows what FOR UPDATE SKIP LOCKED does, with two "relays" at the same time.

Relay A locks the two oldest of three demo rows and keeps its transaction
open. Relay B then asks for rows: plain FOR UPDATE waits on A's lock (we give
up after 1 s), while SKIP LOCKED instantly takes the one row nobody holds.
The demo rows are created as DEAD so the real relay never touches them, and
only those rows are deleted at the end. Run from the project root:

    uv run python -m learning.examples.s4_1.skip_locked_demo
"""

import asyncio

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.session import create_db_engine

DEMO_TYPE = "demo.skip_locked"
PICK = (
    "SELECT id FROM outbox_events WHERE type = :t AND id = ANY(:ids) "
    "ORDER BY id LIMIT :n FOR UPDATE"
)


async def main() -> None:
    engine = create_db_engine()
    ids: list[int] = []
    try:
        async with engine.begin() as conn:
            for n in range(3):
                new_id = await conn.scalar(
                    text(
                        "INSERT INTO outbox_events (type, aggregate_id, payload, status) "
                        "VALUES (:t, :a, '{}', 'DEAD') RETURNING id"
                    ),
                    {"t": DEMO_TYPE, "a": f"demo-{n}"},
                )
                ids.append(int(new_id))
        print(f"created demo rows {ids}")

        async with engine.connect() as relay_a, engine.connect() as relay_b:
            await relay_a.begin()
            taken = await relay_a.scalars(text(PICK), {"t": DEMO_TYPE, "ids": ids, "n": 2})
            print(f"relay A locked {list(taken)} (transaction still open)")

            await relay_b.begin()
            await relay_b.execute(text("SET LOCAL lock_timeout = '1s'"))
            try:
                await relay_b.scalars(text(PICK), {"t": DEMO_TYPE, "ids": ids, "n": 2})
            except DBAPIError:
                print("relay B, plain FOR UPDATE: waited 1 s for A's lock, then gave up")
            await relay_b.rollback()

            await relay_b.begin()
            skipped = await relay_b.scalars(
                text(PICK + " SKIP LOCKED"), {"t": DEMO_TYPE, "ids": ids, "n": 2}
            )
            print(f"relay B, FOR UPDATE SKIP LOCKED: got {list(skipped)} at once")
            await relay_b.rollback()
            await relay_a.rollback()
    finally:
        if ids:
            async with engine.begin() as conn:
                await conn.execute(
                    text("DELETE FROM outbox_events WHERE id = ANY(:ids)"), {"ids": ids}
                )
            print(f"deleted demo rows {ids}")
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
