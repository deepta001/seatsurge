"""Adversarial test 15: self-registration can never create an ADMIN (CLAUDE.md section 9)."""

import inspect

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.services.auth import register_user

SIGNUP = {"email": "mallory@example.com", "username": "mallory", "password": "a long password!"}


async def user_count(db_engine: AsyncEngine) -> int:
    async with db_engine.connect() as connection:
        count = await connection.scalar(text("SELECT count(*) FROM users"))
    return int(count or 0)


async def test_asking_for_the_admin_role_is_rejected_and_creates_nothing(
    client: AsyncClient, db_engine: AsyncEngine
) -> None:
    response = await client.post("/auth/register", json={**SIGNUP, "role": "ADMIN"})

    assert response.status_code == 422
    assert await user_count(db_engine) == 0


async def test_other_privilege_fields_are_rejected_too(
    client: AsyncClient, db_engine: AsyncEngine
) -> None:
    for sneaky_field in ({"is_admin": True}, {"Role": "ADMIN"}, {"id": 1}):
        response = await client.post("/auth/register", json={**SIGNUP, **sneaky_field})
        assert response.status_code == 422
    assert await user_count(db_engine) == 0


async def test_a_normal_registration_is_stored_as_user(
    client: AsyncClient, db_engine: AsyncEngine
) -> None:
    response = await client.post("/auth/register", json=SIGNUP)

    assert response.status_code == 201
    assert response.json()["role"] == "USER"
    async with db_engine.connect() as connection:
        stored_role = await connection.scalar(
            text("SELECT role FROM users WHERE username = 'mallory'")
        )
    assert stored_role == "USER"


def test_the_service_has_no_way_to_choose_a_role() -> None:
    # Even code inside the app can't pass a role to the registration service.
    assert "role" not in inspect.signature(register_user).parameters
