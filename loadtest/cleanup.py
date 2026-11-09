"""Delete exactly what the last load-test run created (S8.3).

    uv run python -m loadtest.cleanup

Reads loadtest/run.json (from prepare.py) and loadtest/created.json (from
the locustfile) and deletes those rows and Redis keys by id and by name:
never whole tables, never key patterns that could match other data.
"""

import asyncio
import json
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.db.session import create_db_engine
from app.redis.client import create_redis_client
from app.redis.keys import (
    EVENTS_CHANGED_KEY,
    HOLDS_CONFIRMING_KEY,
    HOLDS_EXPIRY_KEY,
    ORDERS_STREAM_KEY,
    hold_key,
    idempotency_key,
    inventory_key,
    rehydrate_lock_key,
    seats_returned_key,
    user_hold_key,
)
from app.redis.rate_limit import rate_limit_key

HERE = Path(__file__).parent
RUN_FILE, CREATED_FILE = HERE / "run.json", HERE / "created.json"

ORDER_IDS = text("SELECT id::text FROM orders WHERE event_id = :e")
OUTBOX_IDS = text("SELECT id FROM outbox_events WHERE aggregate_id = ANY(:orders)")


async def delete_rows(run: dict[str, Any]) -> list[str]:
    """Database rows, children first. Returns the run's order ids (for the stream)."""
    engine = create_db_engine()
    try:
        async with engine.begin() as c:
            event = {"e": run["event_id"]}
            orders = list((await c.scalars(ORDER_IDS, event)).all())
            outbox = list((await c.scalars(OUTBOX_IDS, {"orders": orders})).all())
            await c.execute(
                text("DELETE FROM processed_messages WHERE message_id = ANY(:i)"), {"i": outbox}
            )
            await c.execute(text("DELETE FROM outbox_events WHERE id = ANY(:i)"), {"i": outbox})
            await c.execute(text("DELETE FROM tickets WHERE event_id = :e"), event)
            await c.execute(text("DELETE FROM orders WHERE event_id = :e"), event)
            await c.execute(text("DELETE FROM tiers WHERE event_id = :e"), event)
            await c.execute(text("DELETE FROM events WHERE id = :e"), event)
            users = [*run["user_ids"], run["admin_id"]]
            await c.execute(
                text("DELETE FROM refresh_tokens WHERE user_id = ANY(:u)"), {"u": users}
            )
            await c.execute(text("DELETE FROM users WHERE id = ANY(:u)"), {"u": users})
    finally:
        await engine.dispose()
    return orders


async def delete_redis(run: dict[str, Any], created: dict[str, Any], orders: list[str]) -> None:
    redis = create_redis_client()
    try:
        event_id, tier_id = run["event_id"], run["tier_id"]
        holds = created.get("hold_ids", [])
        keys = [hold_key(h) for h in holds]
        keys += [idempotency_key(user, key) for user, key in created.get("idempotency_keys", [])]
        keys += [user_hold_key(event_id, u) for u in run["user_ids"]]
        keys += [rate_limit_key("holds", str(u)) for u in run["user_ids"]]
        keys += [seats_returned_key(o) for o in orders]
        keys += [inventory_key(event_id, tier_id), rehydrate_lock_key(event_id, tier_id)]
        for start in range(0, len(keys), 500):  # in chunks, to keep each command small
            await redis.delete(*keys[start : start + 500])
        if holds:
            await redis.zrem(HOLDS_EXPIRY_KEY, *holds)
            await redis.zrem(HOLDS_CONFIRMING_KEY, *holds)
        await redis.srem(EVENTS_CHANGED_KEY, str(event_id))
        # This run's order messages only, matched by order id in the payload.
        wanted = set(orders)
        entries: Any = await redis.xrange(ORDERS_STREAM_KEY)
        for entry_id, fields in entries:
            payload = json.loads(fields.get("payload", "{}"))
            if payload.get("order_id") in wanted:
                await redis.xdel(ORDERS_STREAM_KEY, entry_id)
    finally:
        await redis.aclose()


async def main() -> None:
    if not RUN_FILE.exists():
        raise SystemExit("no loadtest/run.json: nothing to clean up")
    run = json.loads(RUN_FILE.read_text(encoding="utf-8"))
    created = json.loads(CREATED_FILE.read_text(encoding="utf-8")) if CREATED_FILE.exists() else {}
    orders = await delete_rows(run)
    await delete_redis(run, created, orders)
    RUN_FILE.unlink()
    CREATED_FILE.unlink(missing_ok=True)
    print(f"cleaned up run {run['run']}: event {run['event_id']}, {len(run['user_ids'])} buyers")


if __name__ == "__main__":
    asyncio.run(main())
