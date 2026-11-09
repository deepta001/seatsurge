"""Buying held seats (S6.2b): confirm, tickets with seats, cancel, failure and Redis loss."""

import json
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from prometheus_client import REGISTRY
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.job_errors import PermanentError
from app.core.tokens import create_access_token
from app.db.models import UserRole
from app.redis.keys import seat_key, sold_seats_key
from app.services.payments import MockPaymentProvider
from app.worker import handlers as handlers_module
from app.worker.relay import relay_batch
from tests.outbox import run_pipeline
from tests.sales import Sale, bearer, confirm
from tests.seating import Venue, hold_seats, seat_states


async def query(db_engine: AsyncEngine, sql: str, **params: Any) -> list[Any]:
    async with db_engine.connect() as conn:
        return list((await conn.execute(text(sql), params)).mappings())


async def place_seat_order(
    client: AsyncClient, venue: Venue, user_id: int, seat_ids: list[int]
) -> dict[str, str]:
    held = await hold_seats(client, venue, seat_ids, user_id=user_id)
    assert held.status_code == 201, held.text
    confirmed = await confirm(client, held.json()["hold_id"], user_id)
    assert confirmed.status_code == 202, confirmed.text
    return {"hold_id": held.json()["hold_id"], "order_id": confirmed.json()["order_id"]}


async def test_buying_held_seats_issues_one_ticket_per_seat(
    client: AsyncClient,
    venue: Venue,
    buyers: list[int],
    payments: MockPaymentProvider,
    redis: Redis,
    db_engine: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    s1, s2, *_ = venue.floor
    placed = await place_seat_order(client, venue, buyers[0], [s1, s2])
    [order] = await query(db_engine, "SELECT seat_ids, total_cents, status FROM orders")
    assert (order["seat_ids"], order["total_cents"], order["status"]) == (
        [s1, s2],
        10000,
        "PENDING",
    )

    await run_pipeline(sessions, redis)

    tickets = await query(
        db_engine, "SELECT seat_id, ticket_number, status FROM tickets ORDER BY ticket_number"
    )
    assert [(t["seat_id"], t["ticket_number"], t["status"]) for t in tickets] == [
        (s1, 1, "ISSUED"),
        (s2, 2, "ISSUED"),
    ]
    assert (await query(db_engine, "SELECT status FROM orders"))[0]["status"] == "CONFIRMED"
    # Redis: the seats moved from "held" (seat keys) to "sold" (the sold set).
    assert await redis.exists(seat_key(venue.event_id, s1), seat_key(venue.event_id, s2)) == 0
    assert {str(s1), str(s2)} <= await redis.smembers(sold_seats_key(venue.event_id))
    states = await seat_states(client, venue)
    assert (states[s1], states[s2]) == ("SOLD", "SOLD")
    # Nobody else can hold a sold seat.
    refused = await hold_seats(client, venue, [s1], user_id=buyers[1])
    assert refused.json()["error"] == "seat_taken"
    assert placed["order_id"]


async def test_cancelling_puts_the_seats_back_on_sale_with_new_numbers_next_time(
    client: AsyncClient,
    venue: Venue,
    buyers: list[int],
    payments: MockPaymentProvider,
    redis: Redis,
    db_engine: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    s1 = venue.floor[0]
    placed = await place_seat_order(client, venue, buyers[0], [s1])
    await run_pipeline(sessions, redis)

    cancelled = await client.post(f"/orders/{placed['order_id']}/cancel", headers=bearer(buyers[0]))
    assert cancelled.status_code == 200
    await run_pipeline(sessions, redis)

    assert str(s1) not in await redis.smembers(sold_seats_key(venue.event_id))
    assert (await seat_states(client, venue))[s1] == "AVAILABLE"
    # Someone else buys the same seat: a new ticket number, the seat ISSUED again.
    await place_seat_order(client, venue, buyers[1], [s1])
    await run_pipeline(sessions, redis)
    tickets = await query(
        db_engine, "SELECT seat_id, ticket_number, status FROM tickets ORDER BY ticket_number"
    )
    assert [(t["seat_id"], t["ticket_number"], t["status"]) for t in tickets] == [
        (s1, 1, "CANCELLED"),
        (s1, 2, "ISSUED"),
    ]


async def test_a_redis_flush_with_a_pending_seat_order_never_frees_its_seats(
    client: AsyncClient,
    venue: Venue,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
    redis: Redis,
    db_engine: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    s1, s2, *_ = venue.floor
    await place_seat_order(client, venue, buyers[0], [s1, s2])
    await relay_batch(sessions, redis)  # published, not processed yet

    await redis.flushdb()  # the hold, its seat keys, the sold set and the stream: gone

    # Postgres still knows the PENDING order claims s1 and s2.
    states = await seat_states(client, venue)
    assert (states[s1], states[s2]) == ("HELD", "HELD")
    refused = await hold_seats(client, venue, [s2], user_id=buyers[1])
    assert refused.json()["error"] == "seat_taken"  # the rebuilt sold set includes them

    admin = {"Authorization": f"Bearer {create_access_token(sale.admin_id, UserRole.ADMIN)}"}
    reconciled = await client.post(f"/admin/events/{venue.event_id}/reconcile", headers=admin)
    assert reconciled.json() == {"event_id": venue.event_id, "tiers": [], "requeued_orders": 1}
    await run_pipeline(sessions, redis)

    tickets = await query(db_engine, "SELECT seat_id FROM tickets ORDER BY seat_id")
    assert [t["seat_id"] for t in tickets] == [s1, s2]
    states = await seat_states(client, venue)
    assert (states[s1], states[s2]) == ("SOLD", "SOLD")


async def test_a_failed_seat_order_gives_its_seats_back(
    client: AsyncClient,
    venue: Venue,
    buyers: list[int],
    payments: MockPaymentProvider,
    redis: Redis,
    db_engine: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s1, s2, *_ = venue.floor
    await place_seat_order(client, venue, buyers[0], [s1, s2])
    await relay_batch(sessions, redis)
    # Lose the hold too (as after a flush), so the seats are only in the rebuilt sold set.
    await redis.flushdb()
    assert (await hold_seats(client, venue, [venue.floor[5]], user_id=buyers[2])).status_code == 201
    assert {str(s1), str(s2)} <= await redis.smembers(sold_seats_key(venue.event_id))

    async def always_permanent(*args: Any, **kwargs: Any) -> Any:
        raise PermanentError("simulated: this order can't be fulfilled")

    monkeypatch.setattr(handlers_module, "issue_tickets", always_permanent)
    # Re-send the order (as reconcile would after a flush) to the now-failing worker.
    async with db_engine.begin() as conn:
        await conn.execute(text("UPDATE outbox_events SET status = 'PENDING'"))
    await run_pipeline(sessions, redis)

    assert (await query(db_engine, "SELECT status FROM orders"))[0]["status"] == "FAILED"
    sold = await redis.smembers(sold_seats_key(venue.event_id))
    assert str(s1) not in sold and str(s2) not in sold
    states = await seat_states(client, venue)
    assert (states[s1], states[s2]) == ("AVAILABLE", "AVAILABLE")
    assert (await hold_seats(client, venue, [s1, s2], user_id=buyers[1])).status_code == 201


async def test_finishing_never_creates_a_half_built_sold_set(
    client: AsyncClient,
    venue: Venue,
    buyers: list[int],
    payments: MockPaymentProvider,
    redis: Redis,
    db_engine: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    s1, s2, s3, *_ = venue.floor
    first = await place_seat_order(client, venue, buyers[0], [s1])
    await run_pipeline(sessions, redis)  # s1 sold
    await place_seat_order(client, venue, buyers[1], [s2])
    await redis.delete(sold_seats_key(venue.event_id))  # Redis forgets which seats are sold

    await run_pipeline(sessions, redis)  # s2's tickets are issued; finish must not create {s2}

    assert await redis.exists(sold_seats_key(venue.event_id)) == 0
    # The next hold rebuilds the set from Postgres: both s1 and s2 are sold.
    assert (await hold_seats(client, venue, [s1], user_id=buyers[2])).json()[
        "error"
    ] == "seat_taken"
    assert (await hold_seats(client, venue, [s3], user_id=buyers[2])).status_code == 201
    assert first["order_id"]


@pytest.mark.backstop
async def test_a_seat_with_a_live_ticket_stays_sold_when_a_clashing_order_fails(
    client: AsyncClient,
    venue: Venue,
    buyers: list[int],
    payments: MockPaymentProvider,
    redis: Redis,
    db_engine: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The double-sell backstop: two orders claim one seat; Postgres lets only one ticket exist."""
    s1 = venue.floor[0]
    await place_seat_order(client, venue, buyers[0], [s1])
    await run_pipeline(sessions, redis)  # s1 sold to buyer 0

    # A second PENDING order for the same seat, as if Redis had let it through.
    clash_id = uuid.uuid4()
    async with db_engine.begin() as conn:
        tier = await conn.scalar(text("SELECT tier_id FROM seats WHERE id = :s"), {"s": s1})
        await conn.execute(
            text(
                "INSERT INTO orders (id, user_id, event_id, tier_id, quantity, hold_id, "
                "idempotency_key, total_cents, seat_ids) "
                "VALUES (:o, :u, :e, :t, 1, :h, :k, 5000, ARRAY[CAST(:s AS integer)])"
            ),
            {
                "o": clash_id,
                "u": buyers[1],
                "e": venue.event_id,
                "t": tier,
                "h": f"clash-{clash_id}",
                "k": f"clash-{clash_id}",
                "s": s1,
            },
        )
        payload = {
            "order_id": str(clash_id),
            "hold_id": f"clash-{clash_id}",
            "user_id": buyers[1],
            "event_id": venue.event_id,
            "tier_id": tier,
            "quantity": 1,
            "seat_ids": [s1],
        }
        await conn.execute(
            text(
                "INSERT INTO outbox_events (type, aggregate_id, payload) VALUES "
                "('order.placed', :a, CAST(:p AS jsonb))"
            ),
            {"a": str(clash_id), "p": json.dumps(payload)},
        )

    violations = REGISTRY.get_sample_value("invariant_violations_total") or 0.0
    await run_pipeline(sessions, redis)

    # Postgres refused the second ticket; the order FAILED; the seat stays SOLD.
    assert REGISTRY.get_sample_value("invariant_violations_total") == violations + 1
    issued = await query(db_engine, "SELECT order_id FROM tickets WHERE status = 'ISSUED'")
    assert len(issued) == 1
    [clash] = await query(db_engine, "SELECT status FROM orders WHERE id = :o", o=clash_id)
    assert clash["status"] == "FAILED"
    assert str(s1) in await redis.smembers(sold_seats_key(venue.event_id))
    assert (await seat_states(client, venue))[s1] == "SOLD"
