"""S2.9 demo: many buyers on few seats, spread across 3 separate API processes.

Compare with S2.1, where naive check-then-take oversold. Each process has its
own memory, so only Redis (the atomic Lua script) can keep them honest.

Start three API processes first (each in its own terminal), with Docker up:

    uv run python -m uvicorn app.main:app --port 8001
    uv run python -m uvicorn app.main:app --port 8002
    uv run python -m uvicorn app.main:app --port 8003

Then, from the project root:

    uv run python -m learning.examples.s2_9.three_replicas_demo --buyers 1000 --seats 100

Or, with the full Docker stack up (S8.1), send every buyer through nginx:

    uv run python -m learning.examples.s2_9.three_replicas_demo \\
        --url http://127.0.0.1:8080 --skip-naive

It creates a throwaway event, runs the sale, checks Redis and Postgres, runs
the S2.1 naive version for comparison, and always deletes what it created.
"""

import argparse
import asyncio
import secrets
import time
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import text

from app.core.tokens import create_access_token
from app.db.models import EventStatus, SeatingType, UserRole
from app.db.session import create_db_engine, create_session_factory
from app.redis.client import create_redis_client
from app.redis.keys import HOLDS_EXPIRY_KEY, hold_key, idempotency_key, inventory_key
from app.services.auth import create_admin
from app.services.events import EventChanges, TierSpec, create_event, update_event
from learning.examples.s2_1.oversell_demo import run_against_redis

REPLICAS = ["http://127.0.0.1:8001", "http://127.0.0.1:8002", "http://127.0.0.1:8003"]
RUN_ID = uuid.uuid4().hex[:8]  # unique per run, so a crashed run can't block the next
ADMIN_USERNAME = f"demo_s29_{RUN_ID}"
# Exactly what this run creates in Redis, so cleanup deletes only that (never
# key patterns like hold:*, which would also wipe anyone else's data).
USED_IDEMPOTENCY_KEYS: list[tuple[int, str]] = []


async def create_sale(seats: int) -> tuple[int, int]:
    engine = create_db_engine()
    async with create_session_factory(engine)() as session:
        admin = await create_admin(
            session,
            email=f"{ADMIN_USERNAME}@example.com",
            username=ADMIN_USERNAME,
            password=secrets.token_urlsafe(18),
        )
        result = await create_event(
            session,
            created_by=admin.id,
            name=f"Three Replicas Demo {RUN_ID}",
            description=None,
            starts_at=datetime.now(UTC) + timedelta(days=7),
            venue="Arena",
            city="Leeds",
            seating=SeatingType.GENERAL_ADMISSION,
            tiers=[TierSpec("Floor", 5000, seats)],
        )
        await update_event(session, result.event.id, EventChanges(status=EventStatus.PUBLISHED))
    await engine.dispose()
    return result.event.id, result.tiers[0].id


async def run_sale(
    event_id: int, tier_id: int, buyers: int
) -> tuple[list[httpx.Response | BaseException], float]:
    start = asyncio.Event()
    # Generous client limits, so the client itself isn't the bottleneck.
    limits = httpx.Limits(max_connections=buyers, max_keepalive_connections=buyers)
    async with httpx.AsyncClient(limits=limits, timeout=60) as http:

        async def buyer(user_id: int) -> httpx.Response:
            replica = REPLICAS[user_id % len(REPLICAS)]  # round-robin, like nginx
            token = create_access_token(user_id, UserRole.USER)
            key = str(uuid.uuid4())
            USED_IDEMPOTENCY_KEYS.append((user_id, key))
            await start.wait()
            return await http.post(
                f"{replica}/events/{event_id}/holds",
                json={"tier_id": tier_id, "quantity": 1},
                headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key},
            )

        tasks = [asyncio.create_task(buyer(u)) for u in range(1, buyers + 1)]
        await asyncio.sleep(0)
        began = time.perf_counter()
        start.set()
        # return_exceptions: count failures instead of stopping at the first one.
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return list(results), time.perf_counter() - began


async def cleanup(event_id: int | None, tier_id: int | None, hold_ids: list[str]) -> None:
    """Delete ONLY what this run created: its holds, its idempotency keys, its event's keys."""
    redis = create_redis_client()
    try:
        keys = [hold_key(h) for h in hold_ids]
        keys += [idempotency_key(user_id, key) for user_id, key in USED_IDEMPOTENCY_KEYS]
        if event_id is not None and tier_id is not None:
            keys += [inventory_key(event_id, tier_id)]
            keys += [k async for k in redis.scan_iter(f"uhold:{event_id}:*")]  # this event only
        if keys:
            await redis.delete(*keys)
        if hold_ids:
            await redis.zrem(HOLDS_EXPIRY_KEY, *hold_ids)
    finally:
        await redis.aclose()
    engine = create_db_engine()
    async with engine.begin() as conn:
        owner = "SELECT id FROM users WHERE username = :u"
        events = f"SELECT id FROM events WHERE created_by IN ({owner})"
        await conn.execute(
            text(f"DELETE FROM tiers WHERE event_id IN ({events})"), {"u": ADMIN_USERNAME}
        )
        await conn.execute(
            text(f"DELETE FROM events WHERE id IN ({events})"), {"u": ADMIN_USERNAME}
        )
        await conn.execute(text("DELETE FROM users WHERE username = :u"), {"u": ADMIN_USERNAME})
    await engine.dispose()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--buyers", type=int, default=1000)
    parser.add_argument("--seats", type=int, default=100)
    parser.add_argument("--skip-naive", action="store_true")
    parser.add_argument("--url", help="send every buyer here (e.g. nginx) instead")
    args = parser.parse_args()
    if args.url:
        REPLICAS[:] = [args.url]

    event_id: int | None = None
    tier_id: int | None = None
    hold_ids: list[str] = []
    try:
        event_id, tier_id = await create_sale(args.seats)
        results, seconds = await run_sale(event_id, tier_id, args.buyers)

        outcomes: Counter[str] = Counter()
        for result in results:
            if isinstance(result, BaseException):
                outcomes[type(result).__name__] += 1
            else:
                outcomes[str(result.status_code)] += 1
                if result.status_code == 201:
                    hold_ids.append(result.json()["hold_id"])

        redis = create_redis_client()
        left = str(await redis.get(inventory_key(event_id, tier_id)))
        # Count only this run's holds that Redis really recorded.
        hold_records = sum([await redis.exists(hold_key(h)) for h in hold_ids])
        await redis.aclose()

        print(f"Atomic Lua via {', '.join(REPLICAS)}: {args.buyers} buyers, {args.seats} seats")
        print(f"  outcomes  : {dict(sorted(outcomes.items()))}")
        print(f"  Redis     : counter={left}, hold records={hold_records}")
        print(f"  oversold  : {max(0, outcomes['201'] - args.seats)}   ({seconds:.2f}s wall time)")

        if not args.skip_naive:
            naive = await run_against_redis(args.seats, args.buyers)
            print("S2.1 naive check-then-take (same Redis, same numbers):")
            print(
                f"  sold={naive.sold}, counter_after={naive.counter_after}, "
                f"oversold={max(0, naive.sold - args.seats)}"
            )
    finally:
        await cleanup(event_id, tier_id, hold_ids)
        print("demo data cleaned up")


if __name__ == "__main__":
    asyncio.run(main())
