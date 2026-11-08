"""POST /auth/login and GET /me against a real Postgres."""

from httpx import AsyncClient

PASSWORD = "a long enough password"


async def register_and_login(
    client: AsyncClient, email: str = "asha@example.com", password: str = PASSWORD
) -> dict[str, object]:
    await client.post(
        "/auth/register",
        json={"email": "asha@example.com", "username": "asha", "password": PASSWORD},
    )
    response = await client.post("/auth/login", json={"email": email, "password": password})
    result: dict[str, object] = {"status": response.status_code, **response.json()}
    return result


async def test_login_returns_a_bearer_token_that_works_on_me(client: AsyncClient) -> None:
    login = await register_and_login(client)

    assert login["status"] == 200
    assert login["token_type"] == "bearer"
    assert login["expires_in"] == 15 * 60
    me = await client.get("/me", headers={"Authorization": f"Bearer {login['access_token']}"})
    assert me.status_code == 200
    assert me.json() == {"user_id": 1, "role": "USER"}


async def test_login_email_is_case_insensitive(client: AsyncClient) -> None:
    login = await register_and_login(client, email="  ASHA@Example.COM ")

    assert login["status"] == 200


async def test_wrong_password_and_unknown_email_get_the_identical_401(client: AsyncClient) -> None:
    wrong_password = await register_and_login(client, password="not the right password")
    unknown_email = await client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}
    )

    assert wrong_password["status"] == 401
    assert unknown_email.status_code == 401
    # Byte-for-byte the same answer, so login can't reveal who has an account.
    expected = {"error": "invalid_credentials", "message": "Email or password is incorrect."}
    assert {k: v for k, v in wrong_password.items() if k != "status"} == expected
    assert unknown_email.json() == expected


async def test_me_without_a_token_is_401_with_a_bearer_hint(client: AsyncClient) -> None:
    response = await client.get("/me")

    assert response.status_code == 401
    assert response.json()["error"] == "not_authenticated"
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_me_with_a_garbage_token_is_401(client: AsyncClient) -> None:
    response = await client.get("/me", headers={"Authorization": "Bearer not.a.token"})

    assert response.status_code == 401
