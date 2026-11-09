"""Shows a duplicate stream message counted twice without idempotency, and once with it.

The same "2 seats sold" message is delivered twice (as happens when the relay
crashes after XADD but before marking the row PUBLISHED). A naive handler adds
2 twice; the `run_once` wrapper adds it once. Uses its own user, event, tier,
stream and a negative message id that can never match a real outbox row, and
deletes exactly those at the end. Run from the project root:

    uv run python -m learning.examples.s4_4.process_twice_demo
"""

import asyncio
import json
import random

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.db.session import create_db_engine, create_session_factory
from app.redis.client import create_redis_client
from app.worker.consumer import Handler, StreamMessage, consume_batch, ensure_group
from app.worker.idempotency import run_once

STREAM = "demo:s4_4:stream"
GROUP = "demo-workers"


async def deliver_twice(redis: Redis, handler: Handler, message_id: int, tier_id: int) -> None:
    fields = {
        "outbox_id": str(message_id),
        "type": "order.placed",
        "aggregate_id": "demo-order",
        "payload": json.dumps({"tier_id": tier_id, "quantity": 2}),
    }
    await redis.xadd(STREAM, fields)  # type: ignore[arg-type]
    await redis.xadd(STREAM, fields)  # type: ignore[arg-type]  # the duplicate
    await consume_batch(
        redis, {"order.placed": handler}, consumer="demo", block_ms=None, stream=STREAM, group=GROUP
    )


async def sold(engine: AsyncEngine, tier_id: int) -> int:
    async with engine.connect() as conn:
        return int(await conn.scalar(text("SELECT sold FROM tiers WHERE id = :t"), {"t": tier_id}))


async def main() -> None:
    engine = create_db_engine()
    sessions = create_session_factory(engine)
    redis = create_redis_client()
    message_id = -random.randint(1, 10**9)  # real outbox ids are always positive
    user_id = event_id = tier_id = None
    try:
        async with engine.begin() as conn:
            user_id = await conn.scalar(
                text(
                    "INSERT INTO users (email, username, password_hash) "
                    "VALUES ('twice@example.com', 'twicedemo', 'x') RETURNING id"
                )
            )
            event_id = await conn.scalar(
                text(
                    "INSERT INTO events (name, starts_at, venue, city, seating, created_by) "
                    "VALUES ('Twice', now() + interval '1 day', 'V', 'C', 'GENERAL_ADMISSION', :u) "
                    "RETURNING id"
                ),
                {"u": user_id},
            )
            tier_id = await conn.scalar(
                text(
                    "INSERT INTO tiers (event_id, name, price_cents, capacity) "
                    "VALUES (:e, 'Floor', 5000, 10) RETURNING id"
                ),
                {"e": event_id},
            )
        await ensure_group(redis, STREAM, GROUP)

        async def naive(message: StreamMessage) -> None:
            async with sessions() as session, session.begin():
                await add_sold(session, message)

        await deliver_twice(redis, naive, message_id, tier_id)
        without = await sold(engine, tier_id)
        print(f"WITHOUT idempotency: one 2-seat order delivered twice -> sold = {without}")

        async with engine.begin() as conn:
            await conn.execute(text("UPDATE tiers SET sold = 0 WHERE id = :t"), {"t": tier_id})

        await deliver_twice(redis, run_once(sessions, add_sold), message_id, tier_id)
        with_run_once = await sold(engine, tier_id)
        print(f"WITH run_once:       the same two deliveries        -> sold = {with_run_once}")
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM processed_messages WHERE message_id = :m"), {"m": message_id}
            )
            if event_id is not None:
                await conn.execute(text("DELETE FROM tiers WHERE event_id = :e"), {"e": event_id})
                await conn.execute(text("DELETE FROM events WHERE id = :e"), {"e": event_id})
            if user_id is not None:
                await conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": user_id})
        await redis.delete(STREAM)
        print("deleted the demo's user, event, tier, processed mark and stream")
        await engine.dispose()
        await redis.aclose()


async def add_sold(session: AsyncSession, message: StreamMessage) -> None:
    await session.execute(
        text("UPDATE tiers SET sold = sold + :q WHERE id = :t"),
        {"q": message.payload["quantity"], "t": message.payload["tier_id"]},
    )


if __name__ == "__main__":
    asyncio.run(main())
