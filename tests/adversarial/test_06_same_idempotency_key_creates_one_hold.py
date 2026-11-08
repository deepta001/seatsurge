"""Adversarial test 6: retrying with the same Idempotency-Key creates exactly one hold.

(The "one order" half of test 6 arrives with confirm in Phase C.)
"""

import asyncio

import pytest
from httpx import AsyncClient, Response
from redis.asyncio import Redis

from app.redis import rehydrate
from app.redis.keys import HOLDS_EXPIRY_KEY, inventory_key, rehydrate_lock_key
from tests.sales import Sale, bearer, hold, new_key


async def seats_left(redis: Redis, sale: Sale) -> int:
    return int(await redis.get(inventory_key(sale.event_id, sale.tier_id)) or 0)


async def test_a_retry_replays_the_first_answer_and_takes_no_more_seats(
    client: AsyncClient, redis: Redis, sale: Sale
) -> None:
    key = new_key()

    first = await hold(client, sale, quantity=2, key=key)
    retry = await hold(client, sale, quantity=2, key=key)

    assert first.status_code == retry.status_code == 201
    assert retry.json()["hold_id"] == first.json()["hold_id"]
    assert retry.headers["Idempotent-Replayed"] == "true"
    assert await seats_left(redis, sale) == 48  # taken once, not twice
    assert await redis.zcard(HOLDS_EXPIRY_KEY) == 1


async def test_ten_simultaneous_retries_create_exactly_one_hold(
    client: AsyncClient, redis: Redis, sale: Sale
) -> None:
    key = new_key()
    start = asyncio.Event()

    async def attempt() -> Response:
        await start.wait()
        return await hold(client, sale, quantity=1, key=key)

    tasks = [asyncio.create_task(attempt()) for _ in range(10)]
    await asyncio.sleep(0)
    start.set()
    responses = await asyncio.gather(*tasks)

    created = [r for r in responses if r.status_code == 201]
    busy = [r for r in responses if r.status_code == 409]
    # Every attempt either got the (same) hold or was told to retry shortly.
    assert len(created) + len(busy) == 10
    assert len({r.json()["hold_id"] for r in created}) == 1
    assert {r.json()["error"] for r in busy} <= {"request_in_progress"}
    assert await seats_left(redis, sale) == 49
    assert await redis.zcard(HOLDS_EXPIRY_KEY) == 1


async def test_the_same_key_with_a_different_request_is_422(
    client: AsyncClient, redis: Redis, sale: Sale
) -> None:
    key = new_key()
    await hold(client, sale, quantity=1, key=key)

    reused = await hold(client, sale, quantity=3, key=key)

    assert reused.status_code == 422
    assert reused.json()["error"] == "idempotency_key_reused"
    assert await seats_left(redis, sale) == 49


async def test_keys_belong_to_one_user(client: AsyncClient, redis: Redis, sale: Sale) -> None:
    key = new_key()

    alice = await hold(client, sale, user_id=1, key=key)
    bob = await hold(client, sale, user_id=2, key=key)

    # The same key string from two users is two different requests.
    assert alice.status_code == bob.status_code == 201
    assert alice.json()["hold_id"] != bob.json()["hold_id"]


async def test_a_final_refusal_is_replayed_too(
    client: AsyncClient, redis: Redis, sale: Sale
) -> None:
    await redis.set(inventory_key(sale.event_id, sale.tier_id), 0)
    key = new_key()
    first = await hold(client, sale, key=key)
    # Seats come back, but this key's answer was already "sold out".
    await redis.set(inventory_key(sale.event_id, sale.tier_id), 5)

    retry = await hold(client, sale, key=key)

    assert first.status_code == retry.status_code == 409
    assert retry.json() == first.json()
    assert await seats_left(redis, sale) == 5


async def test_a_temporary_503_is_not_stored_so_a_retry_can_succeed(
    client: AsyncClient, redis: Redis, sale: Sale, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Make a genuine 503: the counter is missing and another process holds the
    # rebuild lock without finishing (see adversarial test 12).
    monkeypatch.setattr(rehydrate, "WAIT_SECONDS", 0.2)
    lock = rehydrate_lock_key(sale.event_id, sale.tier_id)
    await redis.delete(inventory_key(sale.event_id, sale.tier_id))
    await redis.set(lock, "someone-else", ex=10)
    key = new_key()
    first = await hold(client, sale, key=key)
    await redis.delete(lock)  # the stuck rebuilder goes away

    retry = await hold(client, sale, key=key)

    assert first.status_code == 503
    assert retry.status_code == 201


async def test_the_header_is_required(client: AsyncClient, sale: Sale) -> None:
    response = await client.post(
        f"/events/{sale.event_id}/holds",
        json={"tier_id": sale.tier_id, "quantity": 1},
        headers=bearer(1),
    )
    assert response.status_code == 422
