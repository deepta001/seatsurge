"""POST /holds/{id}/confirm against real Postgres and Redis (CLAUDE.md section 7.2)."""

import asyncio
import json
from typing import Any

import pytest
from httpx import AsyncClient, Response
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import create_session_factory
from app.redis.keys import (
    HOLDS_CONFIRMING_KEY,
    HOLDS_EXPIRY_KEY,
    ORDERS_STREAM_KEY,
    hold_key,
    inventory_key,
)
from app.services import orders as orders_service
from app.services.payments import MockPaymentProvider
from app.worker.relay import relay_batch
from tests.sales import Sale, bearer, confirm, hold, new_key, stream_messages

PRICE = 5000  # the `sale` fixture's Floor tier price, in cents


async def rows(db_engine: AsyncEngine, sql: str) -> list[Any]:
    async with db_engine.connect() as connection:
        return list((await connection.execute(text(sql))).mappings())


async def hold_state(redis: Redis, hold_id: str) -> tuple[str | None, bool, bool]:
    """(status, listed in holds:expiry, listed in holds:confirming)."""
    raw_status = await redis.hget(hold_key(hold_id), "status")
    status = None if raw_status is None else str(raw_status)
    in_expiry = await redis.zscore(HOLDS_EXPIRY_KEY, hold_id) is not None
    in_confirming = await redis.zscore(HOLDS_CONFIRMING_KEY, hold_id) is not None
    return status, in_expiry, in_confirming


@pytest.fixture
async def held(
    client: AsyncClient, sale: Sale, buyers: list[int], payments: MockPaymentProvider
) -> str:
    """Buyer 1 holds 3 seats; returns the hold id."""
    response = await hold(client, sale, user_id=buyers[0], quantity=3)
    assert response.status_code == 201
    hold_id: str = response.json()["hold_id"]
    return hold_id


async def test_confirm_creates_a_pending_order_and_its_outbox_row_together(
    client: AsyncClient,
    redis: Redis,
    db_engine: AsyncEngine,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
    held: str,
) -> None:
    response = await confirm(client, held, buyers[0])

    assert response.status_code == 202
    order_id = response.json()["order_id"]
    assert response.json()["status"] == "PENDING"
    [order] = await rows(db_engine, "SELECT * FROM orders")
    assert str(order["id"]) == order_id
    assert (order["user_id"], order["quantity"], order["tier_id"]) == (buyers[0], 3, sale.tier_id)
    assert order["total_cents"] == 3 * PRICE  # the database's price x the hold's quantity
    [event] = await rows(db_engine, "SELECT * FROM outbox_events")
    assert (event["type"], event["status"], event["aggregate_id"]) == (
        "order.placed",
        "PENDING",
        order_id,
    )
    assert event["payload"]["hold_id"] == held
    assert event["payload"]["quantity"] == 3
    # The hold is being bought: kept away from the expiry sweeper, seats still taken.
    assert await hold_state(redis, held) == ("CONFIRMING", False, True)
    assert await redis.get(inventory_key(sale.event_id, sale.tier_id)) == "47"
    assert len(payments._charges_by_key) == 1


async def test_a_retry_with_the_same_key_replays_the_same_order(
    client: AsyncClient, db_engine: AsyncEngine, buyers: list[int], held: str
) -> None:
    key = new_key()

    first = await confirm(client, held, buyers[0], key=key)
    retry = await confirm(client, held, buyers[0], key=key)

    assert retry.json() == first.json()
    assert retry.headers["Idempotent-Replayed"] == "true"
    assert len(await rows(db_engine, "SELECT id FROM orders")) == 1


async def test_confirming_again_with_a_new_key_returns_the_existing_order(
    client: AsyncClient, db_engine: AsyncEngine, buyers: list[int], held: str
) -> None:
    first = await confirm(client, held, buyers[0])
    again = await confirm(client, held, buyers[0])  # fresh key: not a replay

    assert again.status_code == 202
    assert again.json()["order_id"] == first.json()["order_id"]
    assert len(await rows(db_engine, "SELECT id FROM orders")) == 1


@pytest.mark.parametrize(
    ("token", "status", "error"),
    [
        ("tok_declined", 402, "payment_declined"),
        ("tok_unavailable", 503, "payment_unavailable"),
        ("not-a-token", 422, "invalid_payment_token"),
    ],
)
async def test_a_failed_payment_gives_the_hold_back_and_writes_nothing(
    client: AsyncClient,
    redis: Redis,
    db_engine: AsyncEngine,
    buyers: list[int],
    held: str,
    token: str,
    status: int,
    error: str,
) -> None:
    response = await confirm(client, held, buyers[0], token=token)

    assert (response.status_code, response.json()["error"]) == (status, error)
    assert await hold_state(redis, held) == ("HELD", True, False)  # back on the sweeper's list
    assert await rows(db_engine, "SELECT id FROM orders") == []
    assert await rows(db_engine, "SELECT id FROM outbox_events") == []
    # ...and the user can try again with a good card.
    assert (await confirm(client, held, buyers[0])).status_code == 202


async def test_an_expired_hold_is_410(
    client: AsyncClient, redis: Redis, db_engine: AsyncEngine, buyers: list[int], held: str
) -> None:
    await redis.hset(hold_key(held), "expires_at", 1)  # long ago

    response = await confirm(client, held, buyers[0])

    assert (response.status_code, response.json()["error"]) == (410, "hold_expired")
    assert await rows(db_engine, "SELECT id FROM orders") == []


async def test_a_cancelled_hold_is_410(
    client: AsyncClient, db_engine: AsyncEngine, buyers: list[int], held: str
) -> None:
    await client.delete(f"/holds/{held}", headers=bearer(buyers[0]))

    response = await confirm(client, held, buyers[0])

    assert response.status_code == 410


async def test_the_purchase_cap_counts_earlier_orders_and_charges_nothing(
    client: AsyncClient,
    redis: Redis,
    db_engine: AsyncEngine,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
) -> None:
    # Buyer 1 already bought 8 seats earlier (an existing order in Postgres).
    async with db_engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO orders (id, user_id, event_id, tier_id, quantity, hold_id, "
                "idempotency_key, status, total_cents) VALUES (gen_random_uuid(), :u, :e, :t, "
                "8, 'earlier-hold', 'earlier-key', 'CONFIRMED', 40000)"
            ),
            {"u": buyers[0], "e": sale.event_id, "t": sale.tier_id},
        )
    hold_id = (await hold(client, sale, user_id=buyers[0], quantity=3)).json()["hold_id"]

    # 8 bought + 3 more = 11 > the cap of 10.
    response = await confirm(client, hold_id, buyers[0])

    assert (response.status_code, response.json()["error"]) == (409, "purchase_limit_exceeded")
    assert payments._charges_by_key == {}  # refused before charging anything
    assert (await hold_state(redis, hold_id))[0] == "HELD"


async def test_if_saving_fails_after_payment_the_charge_is_refunded_and_the_hold_restored(
    client: AsyncClient,
    redis: Redis,
    db_engine: AsyncEngine,
    buyers: list[int],
    payments: MockPaymentProvider,
    held: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_check = orders_service._check_purchase_cap
    calls = 0

    async def fails_the_second_time(*args: Any) -> None:
        # The 2nd cap check runs inside the write transaction, after the charge.
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("database went away")
        await real_check(*args)

    monkeypatch.setattr(orders_service, "_check_purchase_cap", fails_the_second_time)

    with pytest.raises(RuntimeError):
        await confirm(client, held, buyers[0])

    [charge] = payments._charges_by_key.values()
    assert payments.refunded == {charge.charge_id}
    assert await hold_state(redis, held) == ("HELD", True, False)
    assert await rows(db_engine, "SELECT id FROM orders") == []


async def test_ten_simultaneous_confirms_of_one_hold_make_one_order(
    client: AsyncClient, db_engine: AsyncEngine, buyers: list[int], held: str
) -> None:
    start = asyncio.Event()

    async def attempt() -> Response:
        await start.wait()
        return await confirm(client, held, buyers[0])  # each with its own key

    tasks = [asyncio.create_task(attempt()) for _ in range(10)]
    await asyncio.sleep(0)
    start.set()
    responses = await asyncio.gather(*tasks)

    ok = [r for r in responses if r.status_code == 202]
    busy = [r for r in responses if r.status_code == 409]
    assert len(ok) + len(busy) == 10
    assert len({r.json()["order_id"] for r in ok}) == 1
    assert {r.json()["error"] for r in busy} <= {"confirm_in_progress"}
    assert len(await rows(db_engine, "SELECT id FROM orders")) == 1


async def test_confirm_needs_a_login_and_an_idempotency_key(
    client: AsyncClient, buyers: list[int], held: str
) -> None:
    no_login = await client.post(
        f"/holds/{held}/confirm",
        json={"payment_token": "tok_ok"},
        headers={"Idempotency-Key": new_key()},
    )
    no_key = await client.post(
        f"/holds/{held}/confirm", json={"payment_token": "tok_ok"}, headers=bearer(buyers[0])
    )

    assert no_login.status_code == 401
    assert no_key.status_code == 422


async def test_the_relay_publishes_a_confirmed_order_to_the_stream(
    client: AsyncClient,
    redis: Redis,
    db_engine: AsyncEngine,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
    held: str,
) -> None:
    order_id = (await confirm(client, held, buyers[0])).json()["order_id"]

    published = await relay_batch(create_session_factory(db_engine), redis)

    assert published == 1
    [fields] = await stream_messages(redis, ORDERS_STREAM_KEY)
    assert (fields["type"], fields["aggregate_id"]) == ("order.placed", order_id)
    payload = json.loads(fields["payload"])
    assert (payload["order_id"], payload["hold_id"], payload["quantity"]) == (order_id, held, 3)
    [event] = await rows(db_engine, "SELECT status FROM outbox_events")
    assert event["status"] == "PUBLISHED"


async def test_cancelling_a_hold_while_it_is_being_bought_gives_nothing_back(
    client: AsyncClient,
    redis: Redis,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
    held: str,
) -> None:
    assert (await confirm(client, held, buyers[0])).status_code == 202

    cancelled = await client.delete(f"/holds/{held}", headers=bearer(buyers[0]))

    # 204 (the call is harmless) but nothing changes: the order is still being
    # fulfilled, so its seats must not go back on sale. Only the worker may
    # release a CONFIRMING hold, and only after its order FAILED.
    assert cancelled.status_code == 204
    assert await hold_state(redis, held) == ("CONFIRMING", False, True)
    assert await redis.get(inventory_key(sale.event_id, sale.tier_id)) == "47"
