"""S8.2b demo: follow ONE purchase through every container's logs by its correlation id.

Holds and confirms one ticket through nginx, takes the id from the confirm
response's X-Correlation-ID header, then searches the logs of nginx, the 3
api replicas and the worker for it.

With the full stack up (docker compose up -d --build), from the project root:

    uv run python -m learning.examples.s8_2b.trace_a_purchase

It deletes only what it created (rows by id, Redis keys by name).
"""

import asyncio
import json
import secrets
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.tokens import create_access_token
from app.db.models import EventStatus, SeatingType, UserRole
from app.db.session import create_db_engine, create_session_factory
from app.redis.client import create_redis_client
from app.redis.keys import (
    EVENTS_CHANGED_KEY,
    HOLDS_CONFIRMING_KEY,
    HOLDS_EXPIRY_KEY,
    ORDERS_STREAM_KEY,
    hold_key,
    idempotency_key,
    inventory_key,
    user_hold_key,
)
from app.redis.rate_limit import rate_limit_key
from app.services.auth import create_admin, register_user
from app.services.events import EventChanges, TierSpec, create_event, update_event

NGINX = "http://127.0.0.1:8080"
TAG = uuid.uuid4().hex[:8]
CONTAINERS = ["seatsurge-nginx-1", "seatsurge-api-1", "seatsurge-api-2", "seatsurge-api-3"]
CONTAINERS += ["seatsurge-worker-1"]


@dataclass
class Created:
    """Everything this demo creates, so cleanup deletes exactly that."""

    keys: list[str] = field(default_factory=lambda: [str(uuid.uuid4()), str(uuid.uuid4())])
    admin_id: int | None = None
    buyer_id: int | None = None
    event_id: int | None = None
    tier_id: int | None = None
    hold_id: str | None = None
    order_id: str | None = None


def lines_with(correlation_id: str) -> dict[str, list[str]]:
    """Each container's log lines that mention the id."""
    found = {}
    for container in CONTAINERS:
        logs = subprocess.run(["docker", "logs", container], capture_output=True, text=True)
        hits = [line for line in (logs.stdout + logs.stderr).splitlines() if correlation_id in line]
        if hits:
            found[container] = hits
    return found


def summary(line: str) -> str:
    """A short view of one log line: JSON lines by their main fields, nginx's as they are."""
    try:
        entry = json.loads(line)
    except ValueError:
        return line.split(" correlation_id=")[0]
    keep = ("logger", "event", "route", "status", "outbox_id")
    return "  ".join(f"{key}={entry[key]}" for key in keep if key in entry)


async def main() -> None:
    engine = create_db_engine()
    redis = create_redis_client()
    sessions = create_session_factory(engine)
    made = Created()
    try:
        async with sessions() as s:
            password = secrets.token_urlsafe(18)
            made.admin_id = (
                await create_admin(
                    s, email=f"tr-{TAG}@example.com", username=f"tr{TAG}", password=password
                )
            ).id
            made.buyer_id = (
                await register_user(
                    s, email=f"tb-{TAG}@example.com", username=f"tb{TAG}", password=password
                )
            ).id
            created = await create_event(
                s,
                created_by=made.admin_id,
                name=f"S8.2b trace {TAG}",
                description=None,
                starts_at=datetime.now(UTC) + timedelta(days=7),
                venue="Hall",
                city="Leeds",
                seating=SeatingType.GENERAL_ADMISSION,
                tiers=[TierSpec("Floor", 4500, 10)],
            )
            made.event_id, made.tier_id = created.event.id, created.tiers[0].id
            await update_event(s, made.event_id, EventChanges(status=EventStatus.PUBLISHED))

        token = create_access_token(made.buyer_id, UserRole.USER)
        async with httpx.AsyncClient(base_url=NGINX, timeout=30) as http:
            held = await http.post(
                f"/events/{made.event_id}/holds",
                json={"tier_id": made.tier_id, "quantity": 1},
                headers={"Authorization": f"Bearer {token}", "Idempotency-Key": made.keys[0]},
            )
            made.hold_id = held.json()["hold_id"]
            confirmed = await http.post(
                f"/holds/{made.hold_id}/confirm",
                json={"payment_token": "tok_ok"},
                headers={"Authorization": f"Bearer {token}", "Idempotency-Key": made.keys[1]},
            )
        made.order_id = order_id = confirmed.json()["order_id"]
        correlation_id = confirmed.headers["X-Correlation-ID"]
        print(f"confirm -> {confirmed.status_code}, X-Correlation-ID: {correlation_id}")

        await asyncio.sleep(3)  # relay (0.5 s) and worker pick it up
        async with engine.connect() as conn:
            stored = await conn.scalar(
                text("SELECT correlation_id FROM outbox_events WHERE aggregate_id = :o"),
                {"o": order_id},
            )
            status = await conn.scalar(
                text("SELECT status FROM orders WHERE id = :o"), {"o": order_id}
            )
        print(f"outbox row's correlation_id: {stored}; order status now: {status}")
        print("log lines with this id:")
        for container, hits in lines_with(correlation_id).items():
            for line in hits:
                print(f"  {container:22} {summary(line)}")
    finally:
        await cleanup(engine, redis, made)
        await engine.dispose()
        await redis.aclose()
        print("cleaned up the demo's rows and Redis keys")


async def cleanup(engine: AsyncEngine, redis: Redis, made: Created) -> None:
    admin_id, buyer_id, event_id, tier_id = (
        made.admin_id,
        made.buyer_id,
        made.event_id,
        made.tier_id,
    )
    hold_id, order_id = made.hold_id, made.order_id
    if order_id:
        async with engine.begin() as c:
            ids = (
                await c.scalars(
                    text("SELECT id FROM outbox_events WHERE aggregate_id = :o"), {"o": order_id}
                )
            ).all()
            await c.execute(text("DELETE FROM tickets WHERE order_id = :o"), {"o": order_id})
            await c.execute(text("DELETE FROM orders WHERE id = :o"), {"o": order_id})
            for outbox_id in ids:
                await c.execute(
                    text("DELETE FROM processed_messages WHERE message_id = :i"), {"i": outbox_id}
                )
                await c.execute(text("DELETE FROM outbox_events WHERE id = :i"), {"i": outbox_id})
        # This order's stream entries only (matched by the order id in the payload).
        entries: Any = await redis.xrange(ORDERS_STREAM_KEY)  # redis-py's hint is loose
        for entry_id, fields in entries:
            if order_id in str(fields.get("payload", "")):
                await redis.xdel(ORDERS_STREAM_KEY, str(entry_id))
    if hold_id:
        await redis.delete(hold_key(hold_id))
        await redis.zrem(HOLDS_EXPIRY_KEY, hold_id)
        await redis.zrem(HOLDS_CONFIRMING_KEY, hold_id)
    if buyer_id:
        await redis.delete(*(idempotency_key(buyer_id, k) for k in made.keys))
        await redis.delete(rate_limit_key("holds", str(buyer_id)))
    if event_id and tier_id:
        await redis.delete(inventory_key(event_id, tier_id), f"lock:rehydrate:{event_id}:{tier_id}")
        if buyer_id:
            await redis.delete(user_hold_key(event_id, buyer_id))
        await redis.srem(EVENTS_CHANGED_KEY, str(event_id))
    async with engine.begin() as c:
        if event_id:
            await c.execute(text("DELETE FROM tiers WHERE event_id = :e"), {"e": event_id})
            await c.execute(text("DELETE FROM events WHERE id = :e"), {"e": event_id})
        for user_id in (buyer_id, admin_id):
            if user_id:
                await c.execute(
                    text("DELETE FROM refresh_tokens WHERE user_id = :u"), {"u": user_id}
                )
                await c.execute(text("DELETE FROM users WHERE id = :u"), {"u": user_id})


if __name__ == "__main__":
    asyncio.run(main())
