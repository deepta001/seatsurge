"""Oversized request bodies are refused with 413 before the app reads them."""

from collections.abc import Iterator

from fastapi.testclient import TestClient

from app.core.settings import get_settings
from app.main import app

LIMIT = get_settings().max_request_body_bytes  # 16 KB by default


def chunks(total_bytes: int, size: int = 1024) -> Iterator[bytes]:
    """Yield a body piece by piece, as a chunked upload with no Content-Length does."""
    sent = 0
    while sent < total_bytes:
        piece = min(size, total_bytes - sent)
        sent += piece
        yield b"x" * piece


def test_a_declared_oversized_body_is_413() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/auth/register",
            content=b"x" * (LIMIT + 1),
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 413
    assert response.json()["error"] == "payload_too_large"


def test_a_chunked_body_with_no_length_is_stopped_once_it_passes_the_limit() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/auth/register",
            content=chunks(LIMIT * 4),
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 413


def test_a_lying_content_length_is_rejected() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/auth/register",
            content=b"{}",
            headers={"Content-Type": "application/json", "Content-Length": "not-a-number"},
        )

    assert response.status_code == 413


def test_a_normal_body_still_reaches_the_route() -> None:
    with TestClient(app) as client:
        # Small and invalid: validation (422) runs, proving the body got through.
        response = client.post("/auth/register", json={"email": "x"})

    assert response.status_code == 422
