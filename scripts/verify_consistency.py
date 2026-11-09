"""Check that Postgres and Redis agree, and that nothing was oversold (CLAUDE.md section 11).

Run after a sale has finished and the queue has drained:

    uv run python -m scripts.verify_consistency            # every event
    uv run python -m scripts.verify_consistency --event 42 --wait 60

For every tier it checks that:
  - sold <= capacity (nothing oversold);
  - sold == the number of ISSUED tickets == the seats of CONFIRMED orders;
  - no ticket number is beyond next_number;
  - no order is still PENDING (the queue has drained);
  - general admission: the Redis counter exists and equals what Postgres and
    the live holds say it should be (capacity - sold - held - pending).
Reserved seating: the Redis sold set holds exactly the seats with ISSUED
tickets (plus seats of PENDING orders).

Exit code 0 if everything agrees, 1 on any mismatch (so scripts and CI can
use it), 2 if the queue didn't drain within --wait seconds.
"""

import argparse
import asyncio
import sys
import time
from dataclasses import dataclass, field

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.session import create_db_engine, create_session_factory
from app.redis.client import create_redis_client
from app.redis.keys import inventory_key, sold_seats_key
from app.redis.rehydrate import compute_available
from app.redis.seat_scripts import SOLD_SET_MARKER, seats_in_pending_orders, sold_seat_ids

# One row per tier with everything Postgres knows about it, read in one go.
TIERS = text(
    """
    SELECT t.id AS tier_id, t.event_id, e.seating, t.name, t.capacity, t.sold, t.next_number,
           (SELECT count(*) FROM tickets k
             WHERE k.tier_id = t.id AND k.status = 'ISSUED') AS issued,
           (SELECT max(k.ticket_number) FROM tickets k WHERE k.tier_id = t.id) AS max_number,
           (SELECT coalesce(sum(o.quantity), 0) FROM orders o
             WHERE o.tier_id = t.id AND o.status = 'CONFIRMED') AS confirmed_seats,
           (SELECT count(*) FROM orders o
             WHERE o.tier_id = t.id AND o.status = 'PENDING') AS pending_orders
      FROM tiers t
      JOIN events e ON e.id = t.event_id
     WHERE CAST(:event_id AS integer) IS NULL OR t.event_id = :event_id
     ORDER BY t.event_id, t.id
    """
)
UNDRAINED = text(
    """
    SELECT (SELECT count(*) FROM orders WHERE status = 'PENDING')
         + (SELECT count(*) FROM outbox_events WHERE status = 'PENDING')
    """
)


@dataclass(frozen=True)
class TierState:
    """One row of TIERS: what Postgres says about a tier."""

    tier_id: int
    event_id: int
    seating: str
    name: str
    capacity: int
    sold: int
    next_number: int
    issued: int
    max_number: int | None
    confirmed_seats: int
    pending_orders: int

    @property
    def label(self) -> str:
        return f"event {self.event_id} tier {self.tier_id} ({self.name})"


@dataclass
class Report:
    tiers_checked: int = 0
    tickets_issued: int = 0
    oversold: int = 0
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def check_database(t: TierState, report: Report) -> None:
    """Postgres against itself: counters, tickets and orders must tell one story."""
    report.tiers_checked += 1
    report.tickets_issued += t.issued
    report.oversold += max(0, t.sold - t.capacity)
    if t.sold > t.capacity:
        report.problems.append(f"{t.label}: OVERSOLD, sold {t.sold} > capacity {t.capacity}")
    if t.issued != t.sold:
        report.problems.append(f"{t.label}: sold {t.sold} but {t.issued} ISSUED tickets")
    if t.confirmed_seats != t.sold:
        report.problems.append(
            f"{t.label}: sold {t.sold} but CONFIRMED orders hold {t.confirmed_seats} seats"
        )
    if t.max_number is not None and t.max_number > t.next_number:
        report.problems.append(f"{t.label}: ticket number {t.max_number} > next_number")
    if t.pending_orders:
        report.problems.append(f"{t.label}: {t.pending_orders} order(s) still PENDING")


async def check_counter(session: AsyncSession, redis: Redis, t: TierState, report: Report) -> None:
    """General admission: Redis's live counter must match what Postgres + live holds imply."""
    raw = await redis.get(inventory_key(t.event_id, t.tier_id))
    if raw is None:
        report.problems.append(f"{t.label}: Redis counter is MISSING (never treated as 0)")
        return
    counter = int(raw)
    expected = await compute_available(session, redis, t.event_id, t.tier_id)
    if counter != expected:
        report.problems.append(f"{t.label}: Redis counter {counter}, expected {expected}")


async def check_sold_set(
    session: AsyncSession, redis: Redis, event_id: int, report: Report
) -> None:
    members = await redis.smembers(sold_seats_key(event_id))
    if not members:
        return  # not built yet: rebuilt from Postgres on first use (rule 4)
    in_redis = {int(m) for m in members if m != SOLD_SET_MARKER}
    expected = await sold_seat_ids(session, event_id) | await seats_in_pending_orders(
        session, event_id
    )
    if in_redis != expected:
        missing, extra = sorted(expected - in_redis), sorted(in_redis - expected)
        report.problems.append(
            f"event {event_id}: sold set differs (missing {missing}, extra {extra})"
        )


async def wait_until_drained(sessions: async_sessionmaker[AsyncSession], seconds: float) -> bool:
    """Wait until no order and no outbox row is PENDING. False if time ran out."""
    deadline = time.monotonic() + seconds
    while True:
        async with sessions() as session:
            if not await session.scalar(UNDRAINED):
                return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(0.5)


async def verify(
    sessions: async_sessionmaker[AsyncSession], redis: Redis, event_id: int | None = None
) -> Report:
    report = Report()
    async with sessions() as session:
        rows = (await session.execute(TIERS, {"event_id": event_id})).mappings().all()
        tiers = [TierState(**row) for row in rows]
        for tier in tiers:
            check_database(tier, report)
            if tier.seating == "GENERAL_ADMISSION":
                await check_counter(session, redis, tier, report)
        for reserved_event in sorted({t.event_id for t in tiers if t.seating == "RESERVED"}):
            await check_sold_set(session, redis, reserved_event, report)
    if event_id is not None and not tiers:
        report.problems.append(f"event {event_id} has no tiers (does it exist?)")
    return report


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--event", type=int, help="check only this event")
    parser.add_argument("--wait", type=float, default=0, help="seconds to wait for the queue")
    args = parser.parse_args(argv)

    engine = create_db_engine()
    redis = create_redis_client()
    sessions = create_session_factory(engine)
    try:
        if args.wait and not await wait_until_drained(sessions, args.wait):
            print(f"queue not drained after {args.wait:.0f}s (PENDING orders or outbox rows)")
            return 2
        report = await verify(sessions, redis, args.event)
    finally:
        await redis.aclose()
        await engine.dispose()

    print(f"tiers checked:  {report.tiers_checked}")
    print(f"tickets issued: {report.tickets_issued}")
    print(f"oversold:       {report.oversold}")
    for problem in report.problems:
        print(f"MISMATCH  {problem}")
    print("CONSISTENT" if report.ok else f"INCONSISTENT: {len(report.problems)} problem(s)")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
