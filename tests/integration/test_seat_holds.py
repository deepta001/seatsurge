"""Holding specific seats (S6.2): reserve_seats.lua through POST /events/{id}/holds {seat_ids}."""

import asyncio
import random
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient, Response
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.models import EventStatus, SeatingType
from app.db.session import create_session_factory
from app.redis.keys import hold_key, seat_key, sold_seats_key, user_hold_key
from app.services.events import EventChanges, TierSpec, create_event, update_event
from app.services.holds import create_seat_hold
from app.services.payments import MockPaymentProvider
from app.worker.sweeper import now_ms, sweep_expired_holds
from tests.sales import Sale, bearer, confirm, hold, new_key


@dataclass
class Venue:
    event_id: int
    floor: list[int]  # seat ids in the Floor tier (8 seats)
    balcony: list[int]  # seat ids in the Balcony tier (4 seats)


@pytest.fixture
async def venue(sale: Sale, db_engine: AsyncEngine) -> Venue:
    """A published reserved-seating event: Floor x8, Balcony x4 (the app uses the test Redis)."""
    async with create_session_factory(db_engine)() as session:
        created = await create_event(
            session,
            created_by=sale.admin_id,
            name="Theatre",
            description=None,
            starts_at=datetime.now(UTC) + timedelta(days=7),
            venue="Hall",
            city="Leeds",
            seating=SeatingType.RESERVED,
            tiers=[TierSpec("Floor", 5000, 8), TierSpec("Balcony", 3000, 4)],
        )
        await update_event(session, created.event.id, EventChanges(status=EventStatus.PUBLISHED))
    async with db_engine.connect() as conn:
        rows = (
            await conn.execute(
                text("SELECT id, tier_id FROM seats WHERE event_id = :e ORDER BY id"),
                {"e": created.event.id},
            )
        ).all()
    floor_tier = created.tiers[0].id
    return Venue(
        created.event.id,
        [r.id for r in rows if r.tier_id == floor_tier],
        [r.id for r in rows if r.tier_id != floor_tier],
    )


async def hold_seats(
    client: AsyncClient, venue: Venue, seat_ids: list[int], user_id: int = 1, key: str | None = None
) -> Response:
    return await client.post(
        f"/events/{venue.event_id}/holds",
        json={"seat_ids": seat_ids},
        headers={**bearer(user_id), "Idempotency-Key": key or new_key()},
    )


async def seat_states(client: AsyncClient, venue: Venue) -> dict[int, str]:
    seats = (await client.get(f"/events/{venue.event_id}/seats")).json()["seats"]
    return {s["seat_id"]: s["state"] for s in seats}


async def test_holding_seats_marks_them_held(
    client: AsyncClient, venue: Venue, redis: Redis
) -> None:
    s1, s2, *_ = venue.floor

    response = await hold_seats(client, venue, [s1, s2])

    assert response.status_code == 201
    body = response.json()
    assert (body["seat_ids"], body["quantity"]) == ([s1, s2], 2)
    hold_id = body["hold_id"]
    assert await redis.get(seat_key(venue.event_id, s1)) == hold_id
    assert await redis.hget(hold_key(hold_id), "seats") == f"{s1},{s2}"
    states = await seat_states(client, venue)
    assert (states[s1], states[s2], states[venue.floor[2]]) == ("HELD", "HELD", "AVAILABLE")


async def test_one_taken_seat_means_nothing_is_held(
    client: AsyncClient, venue: Venue, redis: Redis
) -> None:
    s1, s2, s3, *_ = venue.floor
    assert (await hold_seats(client, venue, [s1, s2], user_id=1)).status_code == 201

    clash = await hold_seats(client, venue, [s3, s2], user_id=2)  # s2 is taken

    assert clash.status_code == 409
    assert clash.json()["error"] == "seat_taken"
    assert await redis.exists(seat_key(venue.event_id, s3)) == 0  # s3 was NOT taken
    assert await redis.get(user_hold_key(venue.event_id, 2)) is None
    assert (await hold_seats(client, venue, [s3], user_id=2)).status_code == 201


async def test_overlapping_requests_at_once_never_share_a_seat(
    client: AsyncClient, venue: Venue, redis: Redis
) -> None:
    seats = venue.floor  # 8 seats; 60 buyers each want 2 of them
    start = asyncio.Event()

    async def buyer(user_id: int) -> Response:
        wanted = random.sample(seats, 2)
        await start.wait()
        return await hold_seats(client, venue, wanted, user_id=user_id)

    tasks = [asyncio.create_task(buyer(n)) for n in range(1, 61)]
    start.set()
    responses = await asyncio.gather(*tasks)

    won = [r.json() for r in responses if r.status_code == 201]
    assert {r.json()["error"] for r in responses if r.status_code != 201} <= {"seat_taken"}
    taken = [seat for body in won for seat in body["seat_ids"]]
    assert len(taken) == len(set(taken))  # no seat in two holds
    for body in won:
        for seat in body["seat_ids"]:
            assert await redis.get(seat_key(venue.event_id, seat)) == body["hold_id"]


async def test_a_sold_seat_cannot_be_held_even_when_redis_forgot(
    client: AsyncClient, venue: Venue, redis: Redis, db_engine: AsyncEngine
) -> None:
    sold, free = venue.floor[0], venue.floor[1]
    async with db_engine.begin() as conn:
        user = await conn.scalar(
            text(
                "INSERT INTO users (email, username, password_hash) "
                "VALUES ('sold@example.com', 'soldbuyer', 'x') RETURNING id"
            )
        )
        tier = await conn.scalar(text("SELECT tier_id FROM seats WHERE id = :s"), {"s": sold})
        order_id = uuid.uuid4()
        await conn.execute(
            text(
                "INSERT INTO orders (id, user_id, event_id, tier_id, quantity, hold_id, "
                "idempotency_key, total_cents, status) "
                "VALUES (:o, :u, :e, :t, 1, 'h', 'k', 0, 'CONFIRMED')"
            ),
            {"o": order_id, "u": user, "e": venue.event_id, "t": tier},
        )
        await conn.execute(
            text(
                "INSERT INTO tickets (order_id, event_id, tier_id, seat_id, ticket_number) "
                "VALUES (:o, :e, :t, :s, 1)"
            ),
            {"o": order_id, "e": venue.event_id, "t": tier, "s": sold},
        )
    # Redis has no sold set for this event: that must mean "unknown", never "nothing sold".
    assert await redis.exists(sold_seats_key(venue.event_id)) == 0

    assert (await hold_seats(client, venue, [sold])).json()["error"] == "seat_taken"
    assert await redis.smembers(sold_seats_key(venue.event_id)) == {"built", str(sold)}
    assert (await hold_seats(client, venue, [free])).status_code == 201


@pytest.mark.parametrize(
    "case",
    ["other_event", "two_tiers", "made_up", "repeated", "tier_and_seats", "empty", "eleven"],
)
async def test_bad_seat_choices_are_422(
    client: AsyncClient, venue: Venue, sale: Sale, case: str
) -> None:
    f, b = venue.floor, venue.balcony
    bodies: dict[str, dict[str, object]] = {
        "other_event": {"seat_ids": [f[0], 999_999]},
        "two_tiers": {"seat_ids": [f[0], b[0]]},
        "made_up": {"seat_ids": [999_999]},
        "repeated": {"seat_ids": [f[0], f[0]]},
        "tier_and_seats": {"seat_ids": [f[0]], "tier_id": 1, "quantity": 1},
        "empty": {"seat_ids": []},
        "eleven": {"seat_ids": list(range(1, 12))},
    }
    body = bodies[case]

    response = await client.post(
        f"/events/{venue.event_id}/holds",
        json=body,
        headers={**bearer(1), "Idempotency-Key": new_key()},
    )

    assert response.status_code == 422


async def test_each_kind_of_hold_only_works_on_its_kind_of_event(
    client: AsyncClient, venue: Venue, sale: Sale
) -> None:
    by_seat_on_ga = await client.post(
        f"/events/{sale.event_id}/holds",
        json={"seat_ids": [venue.floor[0]]},
        headers={**bearer(1), "Idempotency-Key": new_key()},
    )
    by_count_on_reserved = await client.post(
        f"/events/{venue.event_id}/holds",
        json={"tier_id": 1, "quantity": 1},
        headers={**bearer(1), "Idempotency-Key": new_key()},
    )

    assert (by_seat_on_ga.status_code, by_seat_on_ga.json()["error"]) == (422, "no_seat_map")
    assert by_count_on_reserved.json()["error"] == "seating_not_supported"
    # General-admission holds are unchanged.
    assert (await hold(client, sale, user_id=1, quantity=2)).status_code == 201


async def test_cancelling_a_seat_hold_frees_its_seats(
    client: AsyncClient, venue: Venue, redis: Redis
) -> None:
    s1, s2, *_ = venue.floor
    hold_id = (await hold_seats(client, venue, [s1, s2], user_id=1)).json()["hold_id"]

    cancelled = await client.delete(f"/holds/{hold_id}", headers=bearer(1))

    assert cancelled.status_code == 204
    assert await redis.exists(seat_key(venue.event_id, s1), seat_key(venue.event_id, s2)) == 0
    assert (await seat_states(client, venue))[s1] == "AVAILABLE"
    assert (await hold_seats(client, venue, [s1, s2], user_id=2)).status_code == 201


async def test_an_expired_seat_hold_is_swept_and_its_seats_freed(
    venue: Venue, redis: Redis, db_engine: AsyncEngine
) -> None:
    s1 = venue.floor[0]
    async with create_session_factory(db_engine)() as session:
        held = await create_seat_hold(
            session,
            redis,
            user_id=1,
            event_id=venue.event_id,
            seat_ids=[s1],
            now=datetime.now(UTC) - timedelta(minutes=10),  # already expired
        )

    assert await sweep_expired_holds(redis, now=now_ms()) == 1

    assert await redis.exists(seat_key(venue.event_id, s1)) == 0
    assert await redis.hget(hold_key(held.hold_id), "status") == "EXPIRED"


async def test_releasing_never_frees_a_seat_that_points_at_another_hold(
    client: AsyncClient, venue: Venue, redis: Redis
) -> None:
    s1 = venue.floor[0]
    hold_id = (await hold_seats(client, venue, [s1], user_id=1)).json()["hold_id"]
    await redis.set(seat_key(venue.event_id, s1), "someone-elses-hold")  # should never happen

    await client.delete(f"/holds/{hold_id}", headers=bearer(1))

    assert await redis.get(seat_key(venue.event_id, s1)) == "someone-elses-hold"


async def test_the_per_user_cap_counts_seats(client: AsyncClient, venue: Venue) -> None:
    assert (await hold_seats(client, venue, venue.floor[:6], user_id=1)).status_code == 201
    assert (await hold_seats(client, venue, venue.balcony, user_id=1)).status_code == 201  # 10

    eleventh = await hold_seats(client, venue, [venue.floor[6]], user_id=1)

    assert (eleventh.status_code, eleventh.json()["error"]) == (409, "hold_limit_exceeded")
    assert (await hold_seats(client, venue, [venue.floor[6]], user_id=2)).status_code == 201


async def test_a_retried_seat_hold_returns_the_same_hold(client: AsyncClient, venue: Venue) -> None:
    key = new_key()
    first = await hold_seats(client, venue, [venue.floor[0]], key=key)
    again = await hold_seats(client, venue, [venue.floor[0]], key=key)

    assert again.json() == first.json()


async def test_a_seat_hold_cannot_be_confirmed_yet(
    client: AsyncClient,
    venue: Venue,
    redis: Redis,
    buyers: list[int],
    payments: MockPaymentProvider,
) -> None:
    hold_id = (await hold_seats(client, venue, [venue.floor[0]], user_id=buyers[0])).json()[
        "hold_id"
    ]

    response = await confirm(client, hold_id, buyers[0])

    # Until S6.2b, buying specific seats is refused clearly, and the hold is untouched.
    assert (response.status_code, response.json()["error"]) == (422, "seat_purchase_not_available")
    assert await redis.hget(hold_key(hold_id), "status") == "HELD"
