"""Shows why the order and its follow-up work must be written in ONE transaction.

Scenario: an order is written, then the next write fails. Without a shared
transaction the order is left behind, half-done. With one, both vanish
together. Everything runs inside an outer transaction that is rolled back at
the end, so your database is left untouched. Run from the project root:

    uv run python -m learning.examples.s3_1.transaction_demo
"""

import asyncio
import uuid

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.session import create_db_engine

INSERT_ORDER = text(
    "INSERT INTO orders (id, user_id, event_id, tier_id, quantity, hold_id, idempotency_key, "
    "total_cents) VALUES (:id, :u, :e, :t, 2, :h, :k, 10000)"
)
# ticket_number 0 breaks ck_tickets_ticket_number_positive: our stand-in for
# "the second write failed" (a crash, a constraint, a network error...).
INSERT_BAD_TICKET = text(
    "INSERT INTO tickets (order_id, event_id, tier_id, ticket_number) VALUES (:o, :e, :t, 0)"
)


async def count_orders(conn: AsyncConnection, order_id: uuid.UUID) -> int:
    found = await conn.scalar(text("SELECT count(*) FROM orders WHERE id = :i"), {"i": order_id})
    return int(found or 0)


async def main() -> None:
    engine = create_db_engine()
    try:
        async with engine.connect() as conn:
            outer = await conn.begin()  # rolled back at the end: nothing is kept
            user = await conn.scalar(
                text(
                    "INSERT INTO users (email, username, password_hash) "
                    "VALUES ('txdemo@example.com', 'txdemo', 'x') RETURNING id"
                )
            )
            event = await conn.scalar(
                text(
                    "INSERT INTO events (name, starts_at, venue, city, seating, created_by) "
                    "VALUES ('Tx', now() + interval '1 day', 'V', 'C', 'GENERAL_ADMISSION', :u) "
                    "RETURNING id"
                ),
                {"u": user},
            )
            tier = await conn.scalar(
                text(
                    "INSERT INTO tiers (event_id, name, price_cents, capacity) "
                    "VALUES (:e, 'Floor', 5000, 10) RETURNING id"
                ),
                {"e": event},
            )
            ids = {"u": user, "e": event, "t": tier}

            # 1. Two SEPARATE units of work: the order commits on its own.
            order_a = uuid.uuid4()
            async with conn.begin_nested():  # unit of work 1
                await conn.execute(INSERT_ORDER, {**ids, "id": order_a, "h": "ha", "k": "ka"})
            try:
                async with conn.begin_nested():  # unit of work 2
                    await conn.execute(INSERT_BAD_TICKET, {**ids, "o": order_a})
            except IntegrityError:
                pass
            print("Separate steps : 2nd write failed, order left behind? ", end="")
            print("YES, a half-done order" if await count_orders(conn, order_a) else "no")

            # 2. ONE unit of work: both writes succeed together or not at all.
            order_b = uuid.uuid4()
            try:
                async with conn.begin_nested():
                    await conn.execute(INSERT_ORDER, {**ids, "id": order_b, "h": "hb", "k": "kb"})
                    await conn.execute(INSERT_BAD_TICKET, {**ids, "o": order_b})
            except IntegrityError:
                pass
            print("One transaction: 2nd write failed, order left behind? ", end="")
            print("YES" if await count_orders(conn, order_b) else "no, both rolled back together")

            await outer.rollback()
            print("(outer transaction rolled back: the database is unchanged)")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
