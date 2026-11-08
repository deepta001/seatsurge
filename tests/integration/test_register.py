"""POST /auth/register against a real Postgres (see the fixtures in tests/conftest.py)."""

import asyncio

from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

GOOD_PASSWORD = "a long enough password"


def signup(email: str = "asha@example.com", username: str = "asha") -> dict[str, str]:
    return {"email": email, "username": username, "password": GOOD_PASSWORD}


async def test_register_returns_the_new_user_without_any_password_data(
    client: AsyncClient,
) -> None:
    response = await client.post("/auth/register", json=signup())

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "asha@example.com"
    assert body["username"] == "asha"
    assert body["role"] == "USER"
    assert set(body) == {"id", "email", "username", "role", "created_at"}


async def test_only_an_argon2_hash_is_stored(client: AsyncClient, db_engine: AsyncEngine) -> None:
    await client.post("/auth/register", json=signup())

    async with db_engine.connect() as connection:
        stored = await connection.scalar(text("SELECT password_hash FROM users"))
    assert stored is not None
    assert stored.startswith("$argon2id$")
    assert GOOD_PASSWORD not in stored


async def test_email_is_case_insensitive_and_duplicates_get_a_clean_409(
    client: AsyncClient,
) -> None:
    await client.post("/auth/register", json=signup())

    response = await client.post(
        "/auth/register", json=signup(email="ASHA@Example.com", username="asha2")
    )

    assert response.status_code == 409
    # A stable code and a safe message; no database error text (rule 10).
    assert response.json() == {
        "error": "user_already_exists",
        "message": "That email or username is already registered.",
    }


async def test_duplicate_username_gets_409(client: AsyncClient) -> None:
    await client.post("/auth/register", json=signup())

    response = await client.post("/auth/register", json=signup(email="other@example.com"))

    assert response.status_code == 409


async def test_short_password_and_bad_email_are_rejected_with_422(client: AsyncClient) -> None:
    short = await client.post(
        "/auth/register",
        json={"email": "a@example.com", "username": "abc", "password": "short"},
    )
    bad_email = await client.post(
        "/auth/register",
        json={"email": "not-an-email", "username": "abc", "password": GOOD_PASSWORD},
    )

    assert short.status_code == 422
    assert bad_email.status_code == 422


async def test_ten_simultaneous_signups_with_one_email_create_exactly_one_user(
    client: AsyncClient, db_engine: AsyncEngine
) -> None:
    start = asyncio.Event()

    async def sign_up(number: int) -> Response:
        # Every task waits here, so all 10 requests are released together.
        await start.wait()
        return await client.post(
            "/auth/register", json=signup(email="race@example.com", username=f"racer{number}")
        )

    tasks = [asyncio.create_task(sign_up(n)) for n in range(10)]
    await asyncio.sleep(0)  # let every task reach the barrier
    start.set()
    responses = await asyncio.gather(*tasks)

    statuses = sorted(r.status_code for r in responses)
    assert statuses == [201] + [409] * 9
    async with db_engine.connect() as connection:
        count = await connection.scalar(
            text("SELECT count(*) FROM users WHERE email = 'race@example.com'")
        )
    assert count == 1
