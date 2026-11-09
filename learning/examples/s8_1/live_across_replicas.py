"""S8.1 demo: live updates reach viewers on EVERY replica, through nginx.

Opens 3 SSE streams through nginx (round robin puts one on each api
replica), then makes one hold. The worker container publishes the change
through Redis pub/sub, and every viewer should receive it.

With the full stack up (docker compose up -d --build), from the project root:

    uv run python -m learning.examples.s8_1.live_across_replicas

It deletes only what it created.
"""

import asyncio
import json
import secrets
import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import text

from app.core.tokens import create_access_token
from app.db.models import EventStatus, SeatingType, UserRole
from app.db.session import create_db_engine, create_session_factory
from app.redis.client import create_redis_client
from app.redis.keys import (
    EVENTS_CHANGED_KEY,
    HOLDS_EXPIRY_KEY,
    hold_key,
    idempotency_key,
    inventory_key,
    user_hold_key,
)
from app.redis.rate_limit import rate_limit_key
from app.services.auth import create_admin
from app.services.events import EventChanges, TierSpec, create_event, update_event

NGINX = "http://127.0.0.1:8080"
VIEWERS = 3
BUYER = 930_001
TAG = uuid.uuid4().hex[:8]


async def watch(http: httpx.AsyncClient, event_id: int, seen: list[dict[str, Any]]) -> None:
    async with http.stream("GET", f"/events/{event_id}/stream") as response:
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                seen.append(json.loads(line[len("data: ") :]))


def replica_of_each_stream(event_id: int) -> dict[str, int]:
    """Count, per api container, the stream requests it logged for this event."""
    counts = {}
    for n in range(1, VIEWERS + 1):
        logs = subprocess.run(
            ["docker", "logs", f"seatsurge-api-{n}"], capture_output=True, text=True
        )
        counts[f"api-{n}"] = (logs.stdout + logs.stderr).count(f"/events/{event_id}/stream")
    return counts


async def main() -> None:
    engine = create_db_engine()
    redis = create_redis_client()
    admin_id = event_id = tier_id = None
    hold_id: str | None = None
    idem = str(uuid.uuid4())
    try:
        async with create_session_factory(engine)() as s:
            admin = await create_admin(
                s,
                email=f"live-{TAG}@example.com",
                username=f"live{TAG}",
                password=secrets.token_urlsafe(18),
            )
            admin_id = admin.id
            created = await create_event(
                s,
                created_by=admin_id,
                name=f"S8.1 live {TAG}",
                description=None,
                starts_at=datetime.now(UTC) + timedelta(days=7),
                venue="Hall",
                city="Leeds",
                seating=SeatingType.GENERAL_ADMISSION,
                tiers=[TierSpec("Floor", 4500, 50)],
            )
            event_id, tier_id = created.event.id, created.tiers[0].id
            await update_event(s, event_id, EventChanges(status=EventStatus.PUBLISHED))

        async with httpx.AsyncClient(base_url=NGINX, timeout=None) as http:
            seen: list[list[dict[str, Any]]] = [[] for _ in range(VIEWERS)]
            viewers = []
            for n in range(VIEWERS):  # one at a time, so round robin spreads them
                viewers.append(asyncio.create_task(watch(http, event_id, seen[n])))
                await asyncio.sleep(0.3)
            await asyncio.sleep(1)

            headers = {
                "Authorization": f"Bearer {create_access_token(BUYER, UserRole.USER)}",
                "Idempotency-Key": idem,
            }
            response = await http.post(
                f"/events/{event_id}/holds",
                json={"tier_id": tier_id, "quantity": 3},
                headers=headers,
            )
            hold_id = response.json()["hold_id"]
            await asyncio.sleep(1.5)  # the worker publishes within 0.2 s
            for task in viewers:
                task.cancel()

        print(f"streams per replica: {replica_of_each_stream(event_id)}")
        for n, messages in enumerate(seen, start=1):
            counts = [[t["available"] for t in m.get("tiers", [])] for m in messages]
            print(f"  viewer {n} received: {counts}")
    finally:
        doomed = [rate_limit_key("holds", str(BUYER)), idempotency_key(BUYER, idem)]
        if hold_id:
            doomed.append(hold_key(hold_id))
            await redis.zrem(HOLDS_EXPIRY_KEY, hold_id)
        if event_id and tier_id:
            doomed += [inventory_key(event_id, tier_id), user_hold_key(event_id, BUYER)]
            doomed.append(f"lock:rehydrate:{event_id}:{tier_id}")
            await redis.srem(EVENTS_CHANGED_KEY, str(event_id))
        await redis.delete(*doomed)
        async with engine.begin() as c:
            if event_id:
                await c.execute(text("DELETE FROM tiers WHERE event_id = :e"), {"e": event_id})
                await c.execute(text("DELETE FROM events WHERE id = :e"), {"e": event_id})
            if admin_id:
                await c.execute(text("DELETE FROM users WHERE id = :u"), {"u": admin_id})
        await engine.dispose()
        await redis.aclose()
        print("cleaned up the demo's admin, event, hold and Redis keys")


if __name__ == "__main__":
    asyncio.run(main())
