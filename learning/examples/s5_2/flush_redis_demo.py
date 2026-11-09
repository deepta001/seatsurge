"""Flushes Redis in the middle of a sale and shows reconcile repairing it.

Runs on its OWN throwaway Postgres and Redis containers (testcontainers), so
the FLUSHALL wipes nothing of yours; both containers are removed at the end.
The real API (uvicorn) and the real worker run as separate processes.

Story (20 seats): A buys 6 (tickets issued). B confirms 5 (its message is
published, but no worker has processed it). C holds 4. Then Redis is wiped.
Run from the project root (Docker must be running):

    uv run python -m learning.examples.s5_2.flush_redis_demo
"""

import asyncio
import os
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from alembic import command
from alembic.config import Config
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.redis import RedisContainer

PORT = 8765
API = f"http://127.0.0.1:{PORT}"


def start(module_args: list[str]) -> subprocess.Popen[bytes]:
    """A child process with this process's environment (pointing at the throwaway stack)."""
    return subprocess.Popen(
        [sys.executable, "-m", *module_args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


def wait_for_api() -> None:
    for _ in range(60):
        try:
            if httpx.get(f"{API}/health/ready").status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise RuntimeError("the API did not start")


async def story() -> None:
    # Imported here, AFTER the environment points at the throwaway containers:
    # the app reads its settings when first used.
    from sqlalchemy import text

    from app.core.tokens import create_access_token
    from app.db.models import EventStatus, SeatingType, UserRole
    from app.db.session import create_db_engine, create_session_factory
    from app.redis.client import create_redis_client
    from app.redis.keys import inventory_key
    from app.services.auth import create_admin, register_user
    from app.services.events import EventChanges, TierSpec, create_event, update_event
    from app.worker.relay import relay_batch

    engine = create_db_engine()
    sessions = create_session_factory(engine)
    redis = create_redis_client()
    async with sessions() as s:
        admin = await create_admin(
            s, email="admin@example.com", username="admin", password="a long password!"
        )
        users = {}
        for name in "ABCD":
            user = await register_user(
                s,
                email=f"{name.lower()}@example.com",
                username=name.lower(),
                password="a long password!",
            )
            users[name] = user.id
        created = await create_event(
            s,
            created_by=admin.id,
            name="Flush demo",
            description=None,
            starts_at=datetime.now(UTC) + timedelta(days=7),
            venue="Hall",
            city="Leeds",
            seating=SeatingType.GENERAL_ADMISSION,
            tiers=[TierSpec("Floor", 5000, 20)],
        )
        event_id, tier_id = created.event.id, created.tiers[0].id
        await update_event(s, event_id, EventChanges(status=EventStatus.PUBLISHED))

    def auth(name: str) -> dict[str, str]:
        user_id = admin.id if name == "admin" else users[name]
        role = UserRole.ADMIN if name == "admin" else UserRole.USER
        return {"Authorization": f"Bearer {create_access_token(user_id, role)}"}

    async def state(http: httpx.AsyncClient) -> str:
        async with engine.connect() as c:
            sold = await c.scalar(text("SELECT sold FROM tiers WHERE id = :t"), {"t": tier_id})
            rows = await c.execute(
                text(
                    "SELECT u.username, o.status FROM orders o "
                    "JOIN users u ON u.id = o.user_id ORDER BY 1"
                )
            )
            orders = ", ".join(f"{r.username.upper()}={r.status}" for r in rows)
        avail = await redis.get(inventory_key(event_id, tier_id))
        return f"sold={sold} | Redis counter={avail} | orders: {orders or 'none'}"

    async def hold(http: httpx.AsyncClient, name: str, quantity: int) -> httpx.Response:
        return await http.post(
            f"/events/{event_id}/holds",
            json={"tier_id": tier_id, "quantity": quantity},
            headers={**auth(name), "Idempotency-Key": str(uuid.uuid4())},
        )

    async def confirm(http: httpx.AsyncClient, name: str, hold_id: str) -> httpx.Response:
        return await http.post(
            f"/holds/{hold_id}/confirm",
            json={"payment_token": "tok_ok"},
            headers={**auth(name), "Idempotency-Key": str(uuid.uuid4())},
        )

    async def wait_for(http: httpx.AsyncClient, needle: str, seconds: float = 10) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and needle not in await state(http):
            await asyncio.sleep(0.3)

    async with httpx.AsyncClient(base_url=API) as http:
        worker = start(["app.worker.main"])
        a = await hold(http, "A", 6)
        await confirm(http, "A", a.json()["hold_id"])
        await wait_for(http, "A=CONFIRMED")
        worker.terminate()
        worker.wait()

        b = await hold(http, "B", 5)
        await confirm(http, "B", b.json()["hold_id"])
        await relay_batch(sessions, redis)  # published; no worker running to process it
        c = await hold(http, "C", 4)
        print(f"1. before the flush:  {await state(http)}   (20 - 6 sold - 5 B - 4 C = 5)")

        await redis.flushall()
        print(f"2. FLUSHALL: Redis now has {await redis.dbsize()} keys")

        worker = start(["app.worker.main"])
        await asyncio.sleep(3)
        print(f"3. worker restarted:  {await state(http)}   (B's message was lost)")
        c_confirm = await confirm(http, "C", c.json()["hold_id"])
        print(f"   C confirms the old hold: {c_confirm.status_code} (the hold is gone)")
        d = await hold(http, "D", 3)
        print(
            f"   D holds 3 seats: {d.status_code} (counter rebuilt: 20 - 6 - 5 for B = 9, minus 3)"
        )
        print(f"                      {await state(http)}")

        r = await http.post(f"/admin/events/{event_id}/reconcile", headers=auth("admin"))
        print(f"4. admin reconcile:   {r.json()}")
        await wait_for(http, "B=CONFIRMED")
        print(f"5. after reconcile:   {await state(http)}")
        print("   check: 11 sold + 3 held by D + 6 available = 20 seats, nothing lost or invented")
        worker.terminate()
        worker.wait()
    await engine.dispose()
    await redis.aclose()


def main() -> None:
    print("starting throwaway Postgres and Redis containers...", flush=True)
    with (
        PostgresContainer("postgres:16-alpine", driver="asyncpg") as pg,
        RedisContainer("redis:7-alpine") as rd,
    ):
        db_url = pg.get_connection_url().replace("@localhost:", "@127.0.0.1:")
        os.environ["DATABASE_URL"] = db_url
        os.environ["REDIS_URL"] = f"redis://127.0.0.1:{rd.get_exposed_port(6379)}/0"
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", db_url)
        command.upgrade(config, "head")
        api = start(["uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(PORT)])
        try:
            wait_for_api()
            asyncio.run(story())
        finally:
            api.terminate()
            api.wait()
    print("throwaway containers removed")


if __name__ == "__main__":
    main()
