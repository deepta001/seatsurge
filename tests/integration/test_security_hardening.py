"""The security checklist (CLAUDE.md section 9 and rule 10), one test per item fixed in S7.2."""

from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.api.dependencies import get_db_session
from app.core.settings import Settings, get_settings
from app.main import api_docs_enabled, app

GOOD = {
    "database_url": "postgresql+asyncpg://u:a-real-password@127.0.0.1:5432/db",
    "redis_url": "redis://:a-real-password@127.0.0.1:6379/0",
    "jwt_secret_key": "x" * 40,
}

# Every route the app serves. A new route must be added here on purpose, so
# no test, debug or simulation endpoint can slip in unnoticed (section 9).
EXPECTED_ROUTES = {
    ("GET", "/"),
    ("GET", "/health/live"),
    ("GET", "/health/ready"),
    ("POST", "/auth/register"),
    ("POST", "/auth/login"),
    ("POST", "/auth/refresh"),
    ("POST", "/auth/logout"),
    ("GET", "/me"),
    ("POST", "/events"),
    ("PATCH", "/events/{event_id}"),
    ("DELETE", "/events/{event_id}"),
    ("GET", "/events"),
    ("GET", "/events/{event_id}"),
    ("GET", "/events/{event_id}/seats"),
    ("POST", "/events/{event_id}/holds"),
    ("DELETE", "/holds/{hold_id}"),
    ("POST", "/holds/{hold_id}/confirm"),
    ("POST", "/orders/{order_id}/cancel"),
    ("POST", "/admin/events/{event_id}/reconcile"),
}
DOCS_ROUTES = {"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}


def all_routes(routes: list[Any], prefix: str = "") -> Iterator[tuple[str, str]]:
    """(method, path) for every route, looking inside included routers too."""
    for route in routes:
        inner = getattr(route, "original_router", None)
        if inner is not None:  # an included router (FastAPI wraps them)
            yield from all_routes(inner.routes, prefix + route.include_context.prefix)
            continue
        for method in getattr(route, "methods", None) or set():
            if method not in {"HEAD", "OPTIONS"}:
                yield method, prefix + route.path


def test_the_app_serves_exactly_the_known_routes() -> None:
    served = {(m, path) for m, path in all_routes(app.routes) if path not in DOCS_ROUTES}
    assert served == EXPECTED_ROUTES


def test_settings_refuse_the_placeholder_secrets() -> None:
    for field in GOOD:
        values = {**GOOD, field: GOOD[field].replace("a-real-password", "CHANGE_ME")}
        if field == "jwt_secret_key":
            values[field] = "CHANGE_ME" + "x" * 40
        with pytest.raises(ValidationError, match="CHANGE_ME"):
            Settings(_env_file=None, **values)  # type: ignore[arg-type, call-arg]


def test_settings_refuse_a_wildcard_cors_origin() -> None:
    with pytest.raises(ValidationError, match="explicitly"):
        Settings(_env_file=None, cors_origins=["*"], **GOOD)  # type: ignore[arg-type, call-arg]


def test_api_docs_are_off_in_production() -> None:
    assert api_docs_enabled("local") and api_docs_enabled("test")
    assert not api_docs_enabled("production")


@pytest.fixture
def allowed_origin() -> Iterator[str]:
    """Allow one front-end origin for this test (the app's CORS list is the settings' list)."""
    origin = "https://tickets.example.com"
    get_settings().cors_origins.append(origin)
    yield origin
    get_settings().cors_origins.remove(origin)


async def test_cors_answers_only_listed_origins(client: AsyncClient, allowed_origin: str) -> None:
    def preflight(origin: str) -> dict[str, str]:
        return {
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,idempotency-key",
        }

    allowed = await client.options("/events/1/holds", headers=preflight(allowed_origin))
    stranger = await client.options("/events/1/holds", headers=preflight("https://evil.example"))

    assert allowed.headers["access-control-allow-origin"] == allowed_origin
    assert "access-control-allow-credentials" not in allowed.headers
    assert "access-control-allow-origin" not in stranger.headers


async def test_a_validation_error_never_echoes_what_was_sent(client: AsyncClient) -> None:
    response = await client.post(
        "/auth/register",
        json={"email": "a@example.com", "username": "someone", "password": "tiny-pw"},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "validation_error"
    assert [f["field"] for f in body["fields"]] == ["body.password"]
    assert "tiny-pw" not in response.text  # the password is not sent back


async def test_an_unexpected_error_is_a_generic_500_with_a_correlation_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def broken_database() -> AsyncIterator[object]:
        raise RuntimeError("connection to db-internal-7 failed, password=hunter2")
        yield  # pragma: no cover  (makes this a generator, like the real dependency)

    app.dependency_overrides[get_db_session] = broken_database
    # raise_app_exceptions=False: behave like a real server, which answers the
    # client instead of crashing the test.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as raw_client:
            response = await raw_client.get("/events")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 500
    body = response.json()
    assert body["error"] == "internal_error"
    assert "hunter2" not in response.text and "db-internal-7" not in response.text
    correlation_id = body["correlation_id"]
    assert response.headers["X-Correlation-ID"] == correlation_id
    # The full details ARE in the server's log, under the same id.
    logged = [r for r in caplog.records if correlation_id in r.getMessage()]
    assert logged and logged[0].exc_info is not None
