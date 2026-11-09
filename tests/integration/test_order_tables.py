"""The orders and tickets tables enforce their rules in Postgres itself (real DB)."""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine


@dataclass
class Ids:
    user: int
    other_user: int
    event: int
    tier: int
    seat: int


@pytest.fixture
async def ids(db_engine: AsyncEngine) -> AsyncIterator[Ids]:
    async with db_engine.begin() as conn:
        user = await conn.scalar(
            text(
                "INSERT INTO users (email, username, password_hash) "
                "VALUES ('a@x.com', 'a', 'h') RETURNING id"
            )
        )
        other = await conn.scalar(
            text(
                "INSERT INTO users (email, username, password_hash) "
                "VALUES ('b@x.com', 'b', 'h') RETURNING id"
            )
        )
        event = await conn.scalar(
            text(
                "INSERT INTO events (name, starts_at, venue, city, seating, created_by) "
                "VALUES ('E', now() + interval '7 days', 'V', 'C', 'GENERAL_ADMISSION', :u) "
                "RETURNING id"
            ),
            {"u": user},
        )
        tier = await conn.scalar(
            text(
                "INSERT INTO tiers (event_id, name, price_cents, capacity) "
                "VALUES (:e, 'Floor', 5000, 100) RETURNING id"
            ),
            {"e": event},
        )
        # A real seat: tickets.seat_id is a foreign key to seats (S6.1).
        seat = await conn.scalar(
            text(
                "INSERT INTO seats (event_id, tier_id, label) VALUES (:e, :t, 'Floor-42') "
                "RETURNING id"
            ),
            {"e": event, "t": tier},
        )
    yield Ids(int(user), int(other), int(event), int(tier), int(seat))
    async with db_engine.begin() as conn:
        await conn.execute(
            text("TRUNCATE users, events, tiers, seats, orders, tickets RESTART IDENTITY CASCADE")
        )


async def add_order(conn: AsyncConnection, ids: Ids, **overrides: Any) -> uuid.UUID:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "user_id": ids.user,
        "event_id": ids.event,
        "tier_id": ids.tier,
        "quantity": 2,
        "hold_id": str(uuid.uuid4()),
        "idempotency_key": str(uuid.uuid4()),
        "total_cents": 10_000,
    }
    values.update(overrides)
    await conn.execute(
        text(
            "INSERT INTO orders (id, user_id, event_id, tier_id, quantity, hold_id, "
            "idempotency_key, total_cents) VALUES (:id, :user_id, :event_id, :tier_id, "
            ":quantity, :hold_id, :idempotency_key, :total_cents)"
        ),
        values,
    )
    order_id: uuid.UUID = values["id"]
    return order_id


async def add_ticket(
    conn: AsyncConnection,
    ids: Ids,
    order_id: uuid.UUID,
    number: int,
    seat: int | None = None,
    status: str = "ISSUED",
) -> None:
    await conn.execute(
        text(
            "INSERT INTO tickets (order_id, event_id, tier_id, seat_id, ticket_number, status) "
            "VALUES (:o, :e, :t, :s, :n, :st)"
        ),
        {"o": order_id, "e": ids.event, "t": ids.tier, "s": seat, "n": number, "st": status},
    )


async def violated(db_engine: AsyncEngine, action: Any) -> str | None:
    """Run `action(conn)` in its own transaction; return the constraint that refused it."""
    try:
        async with db_engine.begin() as conn:
            await action(conn)
    except IntegrityError as error:
        driver_error = getattr(error.orig, "__cause__", None)
        return str(getattr(driver_error, "constraint_name", "?"))
    return None


async def test_a_new_order_is_pending_by_default(db_engine: AsyncEngine, ids: Ids) -> None:
    async with db_engine.begin() as conn:
        order_id = await add_order(conn, ids)
        status = await conn.scalar(text("SELECT status FROM orders WHERE id = :i"), {"i": order_id})
    assert status == "PENDING"


async def test_one_hold_can_become_only_one_order(db_engine: AsyncEngine, ids: Ids) -> None:
    async with db_engine.begin() as conn:
        await add_order(conn, ids, hold_id="hold-1")

    assert await violated(db_engine, lambda c: add_order(c, ids, hold_id="hold-1")) == (
        "uq_orders_hold_id"
    )


async def test_an_idempotency_key_is_unique_per_user(db_engine: AsyncEngine, ids: Ids) -> None:
    async with db_engine.begin() as conn:
        await add_order(conn, ids, idempotency_key="key-1")

    same_user = await violated(db_engine, lambda c: add_order(c, ids, idempotency_key="key-1"))
    other_user = await violated(
        db_engine, lambda c: add_order(c, ids, idempotency_key="key-1", user_id=ids.other_user)
    )

    assert same_user == "uq_orders_user_id_idempotency_key"
    assert other_user is None  # the same key from another user is a different request


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"quantity": 0}, "ck_orders_quantity_positive"),
        ({"total_cents": -1}, "ck_orders_total_not_negative"),
    ],
)
async def test_order_amounts_are_checked(
    db_engine: AsyncEngine, ids: Ids, overrides: dict[str, int], constraint: str
) -> None:
    assert await violated(db_engine, lambda c: add_order(c, ids, **overrides)) == constraint


async def test_a_ticket_number_can_be_issued_only_once_per_tier(
    db_engine: AsyncEngine, ids: Ids
) -> None:
    async with db_engine.begin() as conn:
        order_id = await add_order(conn, ids)
        await add_ticket(conn, ids, order_id, number=7)

    assert await violated(db_engine, lambda c: add_ticket(c, ids, order_id, number=7)) == (
        "uq_tickets_issued_number"
    )


async def test_a_seat_can_have_only_one_issued_ticket(db_engine: AsyncEngine, ids: Ids) -> None:
    async with db_engine.begin() as conn:
        order_id = await add_order(conn, ids)
        await add_ticket(conn, ids, order_id, number=1, seat=ids.seat)

    duplicate = await violated(db_engine, lambda c: add_ticket(c, ids, order_id, 2, seat=ids.seat))

    assert duplicate == "uq_tickets_issued_seat"


async def test_cancelled_tickets_do_not_block_a_seat(db_engine: AsyncEngine, ids: Ids) -> None:
    async with db_engine.begin() as conn:
        order_id = await add_order(conn, ids)
        await add_ticket(conn, ids, order_id, number=1, seat=ids.seat, status="CANCELLED")

    # "Partial" index: only ISSUED tickets count, so the seat can be sold again.
    assert (
        await violated(db_engine, lambda c: add_ticket(c, ids, order_id, 2, seat=ids.seat)) is None
    )


async def test_general_admission_tickets_without_seats_never_clash(
    db_engine: AsyncEngine, ids: Ids
) -> None:
    async with db_engine.begin() as conn:
        order_id = await add_order(conn, ids)
        # seat_id is NULL for general admission; NULLs never count as equal.
        for number in range(1, 6):
            await add_ticket(conn, ids, order_id, number=number, seat=None)
        count = await conn.scalar(text("SELECT count(*) FROM tickets"))
    assert count == 5


async def test_ticket_numbers_must_be_positive(db_engine: AsyncEngine, ids: Ids) -> None:
    async with db_engine.begin() as conn:
        order_id = await add_order(conn, ids)

    assert await violated(db_engine, lambda c: add_ticket(c, ids, order_id, number=0)) == (
        "ck_tickets_ticket_number_positive"
    )


async def test_a_ticket_cannot_point_at_a_seat_that_does_not_exist(
    db_engine: AsyncEngine, ids: Ids
) -> None:
    async with db_engine.begin() as conn:
        order_id = await add_order(conn, ids)

    made_up_seat = await violated(db_engine, lambda c: add_ticket(c, ids, order_id, 1, seat=999999))

    assert made_up_seat == "fk_tickets_seat_id_seats"
