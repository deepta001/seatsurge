"""Tests for /health/live and /health/ready, without real Postgres or Redis."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api import health
from app.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    # `with` runs the app's lifespan (startup and shutdown), just like uvicorn does.
    with TestClient(app) as test_client:
        yield test_client


async def always_up(_: object) -> bool:
    return True


async def always_down(_: object) -> bool:
    return False


def test_live_returns_ok(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_returns_200_when_both_services_answer(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(health, "postgres_is_up", always_up)
    monkeypatch.setattr(health, "redis_is_up", always_up)

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"postgres": "ok", "redis": "ok"}}


def test_ready_returns_503_when_redis_is_down(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(health, "postgres_is_up", always_up)
    monkeypatch.setattr(health, "redis_is_up", always_down)

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"postgres": "ok", "redis": "unavailable"},
    }


def test_ready_hides_error_details_when_services_are_unreachable(client: TestClient) -> None:
    # No monkeypatching: the real checks run against port 1, where nothing listens.
    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"postgres": "unavailable", "redis": "unavailable"},
    }
    # Rule 10: the client must never see raw exception text.
    assert "Error" not in response.text
    assert "127.0.0.1" not in response.text
