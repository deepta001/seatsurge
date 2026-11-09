"""Kills the relay on purpose between "published" and "marked PUBLISHED", then shows recovery.

1. Writes an order and its outbox row in one transaction (what confirm does).
2. Starts a relay in a separate process that hard-kills itself (os._exit, like
   kill -9 or a power cut) right after its XADD, before it can commit.
3. Shows the aftermath: the message IS on the stream, the row is still PENDING.
4. Starts the real worker for a few seconds. Its relay publishes the row
   again (a duplicate); its consumer issues the tickets once.

Uses its own user, event, tier and order, refuses to run if any other outbox
row is PENDING (so it never touches someone else's work), and deletes exactly
what it created. Run from the project root:

    uv run python -m learning.examples.s4_7.kill_relay_demo
"""

import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import create_db_engine, create_session_factory
from app.redis.client import create_redis_client
from app.redis.keys import ORDERS_STREAM_KEY
from app.worker.relay import relay_batch

TAG = uuid.uuid4().hex[:8]


async def crashing_relay() -> None:
    """Child-process mode: relay one batch, but die the instant the XADD returns."""
    engine = create_db_engine()
    redis = create_redis_client()
    real_xadd = redis.xadd

    async def xadd_then_die(*args: Any, **kwargs: Any) -> Any:
        entry_id = await real_xadd(*args, **kwargs)
        print(f"   [relay pid {os.getpid()}] published {entry_id} ... and dies before COMMIT")
        sys.stdout.flush()
        os._exit(137)  # no cleanup, no commit, no finally blocks: a real crash

    redis.xadd = xadd_then_die  # type: ignore[method-assign]
    await relay_batch(create_session_factory(engine), redis)


async def state(engine: AsyncEngine, order_id: uuid.UUID, outbox_id: int) -> str:
    redis = create_redis_client()
    try:
        copies = [
            f for _, f in await redis.xrange(ORDERS_STREAM_KEY) if f["outbox_id"] == str(outbox_id)
        ]
    finally:
        await redis.aclose()
    async with engine.connect() as c:
        order = await c.scalar(text("SELECT status FROM orders WHERE id = :o"), {"o": order_id})
        row = await c.scalar(
            text("SELECT status FROM outbox_events WHERE id = :i"), {"i": outbox_id}
        )
        tickets = list(
            await c.scalars(
                text("SELECT ticket_number FROM tickets WHERE order_id = :o ORDER BY 1"),
                {"o": order_id},
            )
        )
    return f"order {order}, outbox row {row}, stream copies {len(copies)}, tickets {tickets}"


async def main() -> None:
    # Print each line at once, so ours and the child process's appear in order.
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    engine = create_db_engine()
    order_id = uuid.uuid4()
    user_id = event_id = outbox_id = None
    try:
        async with engine.begin() as c:
            others = await c.scalar(
                text("SELECT count(*) FROM outbox_events WHERE status = 'PENDING'")
            )
            if others:
                print(f"refusing to run: {others} other outbox row(s) are PENDING on this database")
                return
            user_id = await c.scalar(
                text(
                    "INSERT INTO users (email, username, password_hash) "
                    "VALUES (:e, :u, 'x') RETURNING id"
                ),
                {"e": f"kill-{TAG}@example.com", "u": f"kill{TAG}"},
            )
            event_id = await c.scalar(
                text(
                    "INSERT INTO events (name, starts_at, venue, city, seating, created_by) "
                    "VALUES ('Kill demo', now() + interval '1 day', 'V', 'C', "
                    "'GENERAL_ADMISSION', :u) RETURNING id"
                ),
                {"u": user_id},
            )
            tier_id = await c.scalar(
                text(
                    "INSERT INTO tiers (event_id, name, price_cents, capacity) "
                    "VALUES (:e, 'Floor', 5000, 10) RETURNING id"
                ),
                {"e": event_id},
            )
        # Step 1: the order and its outbox row, together (as confirm does).
        async with engine.begin() as c:
            await c.execute(
                text(
                    "INSERT INTO orders (id, user_id, event_id, tier_id, quantity, hold_id, "
                    "idempotency_key, total_cents) VALUES (:o, :u, :e, :t, 2, :h, :k, 10000)"
                ),
                {
                    "o": order_id,
                    "u": user_id,
                    "e": event_id,
                    "t": tier_id,
                    "h": f"kill-{TAG}",
                    "k": TAG,
                },
            )
            payload = {
                "order_id": str(order_id),
                "hold_id": f"kill-{TAG}",
                "user_id": user_id,
                "event_id": event_id,
                "tier_id": tier_id,
                "quantity": 2,
                "total_cents": 10000,
            }
            outbox_id = await c.scalar(
                text(
                    "INSERT INTO outbox_events (type, aggregate_id, payload) "
                    "VALUES ('order.placed', :a, CAST(:p AS jsonb)) RETURNING id"
                ),
                {"a": str(order_id), "p": json.dumps(payload)},
            )
        print(f"1. committed order + outbox row:  {await state(engine, order_id, outbox_id)}")

        print("2. starting a relay that will be killed right after it publishes:")
        child = [sys.executable, "-m", "learning.examples.s4_7.kill_relay_demo", "--crashing-relay"]
        died = subprocess.run(child, check=False)
        print(f"   relay process exit code: {died.returncode}")
        print(f"3. after the crash:               {await state(engine, order_id, outbox_id)}")

        print("4. starting the real worker (relay + consumer) for a few seconds...")
        worker = subprocess.Popen(
            [sys.executable, "-m", "app.worker.main"], stderr=subprocess.DEVNULL
        )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            await asyncio.sleep(0.5)
            if "CONFIRMED" in await state(engine, order_id, outbox_id):
                break
        worker.terminate()
        worker.wait()
        print(f"   after recovery:                {await state(engine, order_id, outbox_id)}")
    finally:
        await cleanup(engine, order_id, outbox_id, event_id, user_id)
        await engine.dispose()


async def cleanup(
    engine: AsyncEngine,
    order_id: uuid.UUID,
    outbox_id: int | None,
    event_id: int | None,
    user_id: int | None,
) -> None:
    redis = create_redis_client()
    try:
        for entry_id, fields in await redis.xrange(ORDERS_STREAM_KEY):
            if outbox_id is not None and fields.get("outbox_id") == str(outbox_id):
                await redis.xdel(ORDERS_STREAM_KEY, entry_id)
    finally:
        await redis.aclose()
    async with engine.begin() as c:
        if outbox_id is not None:
            await c.execute(
                text("DELETE FROM processed_messages WHERE message_id = :i"), {"i": outbox_id}
            )
            await c.execute(text("DELETE FROM outbox_events WHERE id = :i"), {"i": outbox_id})
        await c.execute(text("DELETE FROM tickets WHERE order_id = :o"), {"o": order_id})
        await c.execute(text("DELETE FROM orders WHERE id = :o"), {"o": order_id})
        if event_id is not None:
            await c.execute(text("DELETE FROM tiers WHERE event_id = :e"), {"e": event_id})
            await c.execute(text("DELETE FROM events WHERE id = :e"), {"e": event_id})
        if user_id is not None:
            await c.execute(text("DELETE FROM users WHERE id = :u"), {"u": user_id})
    print(
        "cleaned up: the demo's user, event, tier, order, tickets, "
        "outbox/processed rows and stream copies"
    )


if __name__ == "__main__":
    if "--crashing-relay" in sys.argv:
        asyncio.run(crashing_relay())
    else:
        asyncio.run(main())
