"""DELETE /holds/{id} over HTTP: a user gives their own hold back."""

from httpx import AsyncClient
from redis.asyncio import Redis

from app.redis.keys import inventory_key
from tests.sales import Sale, bearer, hold


async def seats_left(redis: Redis, sale: Sale) -> int:
    return int(await redis.get(inventory_key(sale.event_id, sale.tier_id)) or 0)


async def test_cancelling_returns_the_seats(client: AsyncClient, redis: Redis, sale: Sale) -> None:
    hold_id = (await hold(client, sale, user_id=3, quantity=4)).json()["hold_id"]
    assert await seats_left(redis, sale) == 46

    response = await client.delete(f"/holds/{hold_id}", headers=bearer(3))

    assert response.status_code == 204
    assert await seats_left(redis, sale) == 50


async def test_cancelling_twice_is_fine_and_returns_seats_once(
    client: AsyncClient, redis: Redis, sale: Sale
) -> None:
    hold_id = (await hold(client, sale, user_id=3, quantity=4)).json()["hold_id"]

    first = await client.delete(f"/holds/{hold_id}", headers=bearer(3))
    second = await client.delete(f"/holds/{hold_id}", headers=bearer(3))

    assert first.status_code == second.status_code == 204
    assert await seats_left(redis, sale) == 50


async def test_someone_elses_hold_looks_like_it_does_not_exist(
    client: AsyncClient, redis: Redis, sale: Sale
) -> None:
    hold_id = (await hold(client, sale, user_id=3, quantity=4)).json()["hold_id"]

    stranger = await client.delete(f"/holds/{hold_id}", headers=bearer(4))
    unknown = await client.delete("/holds/no-such-hold", headers=bearer(4))

    assert stranger.status_code == unknown.status_code == 404
    assert stranger.json() == unknown.json()
    assert await seats_left(redis, sale) == 46  # untouched


async def test_cancelling_needs_a_login(client: AsyncClient, sale: Sale) -> None:
    hold_id = (await hold(client, sale)).json()["hold_id"]

    assert (await client.delete(f"/holds/{hold_id}")).status_code == 401


async def test_after_cancelling_a_capped_user_can_hold_again(
    client: AsyncClient, sale: Sale
) -> None:
    hold_id = (await hold(client, sale, user_id=3, quantity=10)).json()["hold_id"]
    assert (await hold(client, sale, user_id=3)).json()["error"] == "hold_limit_exceeded"

    await client.delete(f"/holds/{hold_id}", headers=bearer(3))

    assert (await hold(client, sale, user_id=3, quantity=10)).status_code == 201
