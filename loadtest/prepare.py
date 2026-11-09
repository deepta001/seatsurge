"""Set up one load-test sale: an event with N seats and M real buyer accounts (S8.3).

    uv run python -m loadtest.prepare --seats 100 --users 1000

Writes loadtest/run.json, which the locustfile reads and loadtest/cleanup.py
uses to delete exactly what this run created. Buyers are real users (orders
need them), inserted in bulk with ONE shared password hash: hashing 1,000
passwords with argon2 would take far longer and isn't what we're measuring.

The Redis counter is deliberately NOT created: the first wave of buyers
finds it missing and must rebuild it once, under the lock (rule 4).
"""

import argparse
import asyncio
import json
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import insert

from app.core.security import hash_password
from app.db.models import EventStatus, SeatingType, User, UserRole
from app.db.session import create_db_engine, create_session_factory
from app.services.auth import create_admin
from app.services.events import EventChanges, TierSpec, create_event, update_event

RUN_FILE = Path(__file__).parent / "run.json"


async def prepare(seats: int, users: int) -> dict[str, object]:
    run = secrets.token_hex(4)
    engine = create_db_engine()
    try:
        async with create_session_factory(engine)() as session:
            # Nobody logs in as these accounts, so the password is thrown away.
            password = secrets.token_urlsafe(24)
            admin = await create_admin(
                session,
                email=f"load-admin-{run}@example.com",
                username=f"load_admin_{run}",
                password=password,
            )
            created = await create_event(
                session,
                created_by=admin.id,
                name=f"Load test {run}",
                description="Created by loadtest/prepare.py",
                starts_at=datetime.now(UTC) + timedelta(days=7),
                venue="Arena",
                city="Leeds",
                seating=SeatingType.GENERAL_ADMISSION,
                tiers=[TierSpec("Floor", 5000, seats)],
            )
            await update_event(
                session, created.event.id, EventChanges(status=EventStatus.PUBLISHED)
            )

            shared_hash = hash_password(password)
            rows = [
                {
                    "email": f"load-{run}-{n}@example.com",
                    "username": f"load_{run}_{n}",
                    "password_hash": shared_hash,
                    "role": UserRole.USER,
                }
                for n in range(users)
            ]
            result = await session.execute(insert(User).returning(User.id), rows)
            user_ids = [int(user_id) for user_id in result.scalars()]
            await session.commit()
    finally:
        await engine.dispose()

    return {
        "run": run,
        "seats": seats,
        "event_id": created.event.id,
        "tier_id": created.tiers[0].id,
        "admin_id": admin.id,
        "user_ids": user_ids,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Create one load-test sale.")
    parser.add_argument("--seats", type=int, default=100)
    parser.add_argument("--users", type=int, default=1000)
    args = parser.parse_args()
    if RUN_FILE.exists():
        raise SystemExit(f"{RUN_FILE} exists: run loadtest/cleanup.py for the last run first")
    details = asyncio.run(prepare(args.seats, args.users))
    RUN_FILE.write_text(json.dumps(details), encoding="utf-8")
    print(
        f"run {details['run']}: event {details['event_id']} with {args.seats} seats, "
        f"{args.users} buyers -> {RUN_FILE.name}"
    )


if __name__ == "__main__":
    main()
