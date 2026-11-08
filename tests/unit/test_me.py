"""GET /me must work from the token alone, without touching the database (CLAUDE.md section 9)."""

from fastapi.testclient import TestClient

from app.core.tokens import create_access_token
from app.db.models import UserRole
from app.main import app


def test_me_answers_from_the_token_even_though_the_database_is_unreachable() -> None:
    # In unit tests DATABASE_URL points at port 1, where nothing listens (see
    # tests/conftest.py). A database query here would fail, so a 200 proves
    # the auth dependency never asked the database.
    token = create_access_token(999, UserRole.ADMIN)

    with TestClient(app) as client:
        response = client.get("/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    # User 999 doesn't exist anywhere. The token alone is trusted until it
    # expires: the documented trade-off of not checking the database.
    assert response.json() == {"user_id": 999, "role": "ADMIN"}
