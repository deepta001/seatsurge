"""Refresh tokens against a real Postgres: rotation, reuse detection, expiry and logout."""

import asyncio
from typing import Any

from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

PASSWORD = "a long enough password"


async def login(client: AsyncClient) -> dict[str, Any]:
    await client.post(
        "/auth/register",
        json={"email": "asha@example.com", "username": "asha", "password": PASSWORD},
    )
    response = await client.post(
        "/auth/login", json={"email": "asha@example.com", "password": PASSWORD}
    )
    assert response.status_code == 200
    tokens: dict[str, Any] = response.json()  # a mix of strings and numbers
    return tokens


async def refresh(client: AsyncClient, refresh_token: str) -> Response:
    return await client.post("/auth/refresh", json={"refresh_token": refresh_token})


async def test_login_also_returns_a_7_day_refresh_token(client: AsyncClient) -> None:
    tokens = await login(client)

    assert len(tokens["refresh_token"]) >= 40
    assert tokens["refresh_expires_in"] == 7 * 24 * 60 * 60


async def test_refresh_gives_a_new_working_pair(client: AsyncClient) -> None:
    first = await login(client)

    response = await refresh(client, first["refresh_token"])

    assert response.status_code == 200
    second = response.json()
    assert second["refresh_token"] != first["refresh_token"]
    me = await client.get("/me", headers={"Authorization": f"Bearer {second['access_token']}"})
    assert me.status_code == 200


async def test_reusing_an_old_refresh_token_revokes_the_whole_family(client: AsyncClient) -> None:
    r1 = (await login(client))["refresh_token"]
    r2 = (await refresh(client, r1)).json()["refresh_token"]

    # An attacker (or a buggy client) replays the already-used r1...
    replay = await refresh(client, r1)
    assert replay.status_code == 401

    # ...so r2, the legitimate latest token, is revoked too. Everyone must log in again.
    assert (await refresh(client, r2)).status_code == 401


async def test_only_the_hash_is_stored(client: AsyncClient, db_engine: AsyncEngine) -> None:
    raw = (await login(client))["refresh_token"]

    async with db_engine.connect() as connection:
        stored = await connection.scalar(text("SELECT token_hash FROM refresh_tokens"))
    assert stored is not None
    assert len(stored) == 64
    assert stored != raw


async def test_an_expired_refresh_token_is_rejected(
    client: AsyncClient, db_engine: AsyncEngine
) -> None:
    raw = (await login(client))["refresh_token"]
    async with db_engine.begin() as connection:
        await connection.execute(
            text("UPDATE refresh_tokens SET expires_at = now() - interval '1 second'")
        )

    assert (await refresh(client, raw)).status_code == 401


async def test_garbage_refresh_token_is_rejected(client: AsyncClient) -> None:
    assert (await refresh(client, "not-a-real-token")).status_code == 401


async def test_logout_revokes_the_refresh_token(client: AsyncClient) -> None:
    raw = (await login(client))["refresh_token"]

    logout = await client.post("/auth/logout", json={"refresh_token": raw})

    assert logout.status_code == 204
    assert (await refresh(client, raw)).status_code == 401


async def test_logout_with_an_unknown_token_still_returns_204(client: AsyncClient) -> None:
    response = await client.post("/auth/logout", json={"refresh_token": "never-issued"})

    assert response.status_code == 204


async def test_a_role_change_takes_effect_at_the_next_refresh(
    client: AsyncClient, db_engine: AsyncEngine
) -> None:
    raw = (await login(client))["refresh_token"]
    async with db_engine.begin() as connection:
        await connection.execute(text("UPDATE users SET role = 'ADMIN' WHERE username = 'asha'"))

    new_access = (await refresh(client, raw)).json()["access_token"]

    me = await client.get("/me", headers={"Authorization": f"Bearer {new_access}"})
    assert me.json()["role"] == "ADMIN"


async def test_five_simultaneous_refreshes_with_one_token_succeed_only_once(
    client: AsyncClient,
) -> None:
    raw = (await login(client))["refresh_token"]
    start = asyncio.Event()

    async def try_refresh() -> int:
        await start.wait()
        return (await refresh(client, raw)).status_code

    tasks = [asyncio.create_task(try_refresh()) for _ in range(5)]
    await asyncio.sleep(0)
    start.set()
    statuses = sorted(await asyncio.gather(*tasks))

    # The conditional UPDATE lets exactly one request claim the token.
    assert statuses == [200, 401, 401, 401, 401]
