"""Adversarial test 4 for reserved seating: a seat is never sold twice.

The general-admission version (test 4) checks tier capacity. This one checks
single seats: the hold expires and someone else takes the seat, Redis is
wiped while orders compete for one seat, and many buyers race through the
whole pipeline. The last line of defence is Postgres's partial unique index
`uq_tickets_issued_seat`: one ISSUED ticket per seat.
"""

import asyncio
import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.job_errors import InvariantViolation
from app.redis.keys import DEAD_LETTER_STREAM_KEY, seat_key, sold_seats_key
from app.services.holds import create_seat_hold
from app.services.payments import MockPaymentProvider
from app.services.tickets import issue_tickets
from app.worker.sweeper import now_ms, sweep_expired_holds
from tests.outbox import run_pipeline
from tests.sales import confirm, stream_messages
from tests.seating import Venue, hold_seats, seat_states


async def make_users(db_engine: AsyncEngine, count: int) -> list[int]:
    """Real user rows (orders need them), inserted directly to keep the test fast."""
    async with db_engine.begin() as conn:
        rows = await conn.scalars(
            text(
                "INSERT INTO users (email, username, password_hash) "
                "SELECT 'seat' || n || '@example.com', 'seat' || n, 'x' "
                "FROM generate_series(1, :count) AS n RETURNING id"
            ),
            {"count": count},
        )
        return list(rows)


async def issued_seats(db_engine: AsyncEngine) -> list[int]:
    async with db_engine.connect() as conn:
        rows = await conn.scalars(
            text("SELECT seat_id FROM tickets WHERE status = 'ISSUED' ORDER BY seat_id")
        )
        return list(rows)


async def test_a_seat_whose_hold_expired_goes_to_the_next_buyer_only(
    client: AsyncClient,
    venue: Venue,
    payments: MockPaymentProvider,
    redis: Redis,
    db_engine: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    first, second = await make_users(db_engine, 2)
    s1 = venue.floor[0]
    async with sessions() as session:
        stale = await create_seat_hold(
            session,
            redis,
            user_id=first,
            event_id=venue.event_id,
            seat_ids=[s1],
            now=datetime.now(UTC) - timedelta(minutes=10),  # its time is already up
        )
    await sweep_expired_holds(redis, now=now_ms())  # the lock on the seat is gone

    held = await hold_seats(client, venue, [s1], user_id=second)
    assert held.status_code == 201
    assert (await confirm(client, held.json()["hold_id"], second)).status_code == 202
    late = await confirm(client, stale.hold_id, first)  # the first buyer comes back
    await run_pipeline(sessions, redis)

    assert (late.status_code, late.json()["error"]) == (410, "hold_expired")
    assert await issued_seats(db_engine) == [s1]  # one ticket, for the second buyer


async def test_a_hold_being_confirmed_is_never_swept_away(
    client: AsyncClient,
    venue: Venue,
    payments: MockPaymentProvider,
    redis: Redis,
    db_engine: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    [buyer] = await make_users(db_engine, 1)
    s1 = venue.floor[0]
    held = await hold_seats(client, venue, [s1], user_id=buyer)
    assert (await confirm(client, held.json()["hold_id"], buyer)).status_code == 202

    # Long after the hold's 5 minutes: the sweeper must leave a CONFIRMING hold alone.
    await sweep_expired_holds(redis, now=now_ms() + 3_600_000)

    assert await redis.get(seat_key(venue.event_id, s1)) == held.json()["hold_id"]
    await run_pipeline(sessions, redis)
    assert await issued_seats(db_engine) == [s1]


async def test_with_redis_wiped_many_orders_for_one_seat_issue_exactly_one_ticket(
    venue: Venue,
    redis: Redis,
    db_engine: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Redis knows nothing; 20 PENDING orders claim the same seat; they're issued all at once."""
    await redis.flushdb()
    buyers = await make_users(db_engine, 20)
    s1 = venue.floor[0]
    order_ids = [uuid.uuid4() for _ in buyers]
    async with db_engine.begin() as conn:
        tier = await conn.scalar(text("SELECT tier_id FROM seats WHERE id = :s"), {"s": s1})
        for order_id, buyer in zip(order_ids, buyers, strict=True):
            await conn.execute(
                text(
                    "INSERT INTO orders (id, user_id, event_id, tier_id, quantity, hold_id, "
                    "idempotency_key, total_cents, seat_ids) "
                    "VALUES (:o, :u, :e, :t, 1, :h, :k, 5000, ARRAY[CAST(:s AS integer)])"
                ),
                {
                    "o": order_id,
                    "u": buyer,
                    "e": venue.event_id,
                    "t": tier,
                    "h": f"wiped-{order_id}",
                    "k": f"wiped-{order_id}",
                    "s": s1,
                },
            )
    start = asyncio.Event()

    async def issue(order_id: uuid.UUID) -> Any:
        await start.wait()  # all at the same moment
        async with sessions() as session, session.begin():
            return await issue_tickets(session, order_id)

    tasks = [asyncio.create_task(issue(order_id)) for order_id in order_ids]
    start.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)

    refused = [r for r in results if isinstance(r, BaseException)]
    assert len(refused) == 19
    assert all(isinstance(r, InvariantViolation) for r in refused)  # that exact error
    assert await issued_seats(db_engine) == [s1]


async def test_many_buyers_racing_through_the_whole_pipeline_never_share_a_seat(
    client: AsyncClient,
    venue: Venue,
    payments: MockPaymentProvider,
    redis: Redis,
    db_engine: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    buyers = await make_users(db_engine, 40)
    seats = venue.floor + venue.balcony  # 12 seats, 40 buyers wanting 1-3 each
    start = asyncio.Event()

    async def buyer(user_id: int) -> str | None:
        tier_seats = random.choice([venue.floor, venue.balcony])
        wanted = random.sample(tier_seats, random.randint(1, 3))
        await start.wait()
        held = await hold_seats(client, venue, wanted, user_id=user_id)
        if held.status_code != 201:
            assert held.json()["error"] == "seat_taken"
            return None
        confirmed = await confirm(client, held.json()["hold_id"], user_id)
        assert confirmed.status_code == 202, confirmed.text
        return str(held.json()["hold_id"])

    tasks = [asyncio.create_task(buyer(user_id)) for user_id in buyers]
    start.set()
    won = [hold_id for hold_id in await asyncio.gather(*tasks) if hold_id]
    await run_pipeline(sessions, redis)

    sold = await issued_seats(db_engine)
    assert sold, "somebody should have bought something"
    assert len(sold) == len(set(sold))  # no seat has two live tickets
    assert set(sold) <= set(seats)
    async with db_engine.connect() as conn:
        statuses = set(await conn.scalars(text("SELECT status FROM orders")))
    assert statuses == {"CONFIRMED"} and len(won) > 0
    assert await stream_messages(redis, DEAD_LETTER_STREAM_KEY) == []  # backstop never needed
    # Redis, Postgres and the seat map all agree on which seats are sold.
    sold_set = await redis.smembers(sold_seats_key(venue.event_id))
    assert sold_set == {"built", *(str(seat) for seat in sold)}
    states = await seat_states(client, venue)
    assert {seat for seat, state in states.items() if state == "SOLD"} == set(sold)
    # Every unsold seat is AVAILABLE (there may be none left, if all 12 sold).
    assert {state for seat, state in states.items() if seat not in sold} <= {"AVAILABLE"}
