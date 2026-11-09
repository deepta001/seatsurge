"""One correlation id follows a purchase: request -> outbox row -> stream -> worker (S8.2b).

Log lines are captured through the same JSON formatter the containers use,
so these tests check the real output, field by field.
"""

import io
import json
import logging
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api.dependencies import get_db_session
from app.core.correlation import correlation_scope
from app.core.log_setup import build_formatter
from app.db.outbox_models import OutboxEvent
from app.main import app
from app.redis.keys import ORDERS_STREAM_KEY
from app.services.payments import MockPaymentProvider
from tests.outbox import run_pipeline
from tests.sales import Sale, bearer, hold, new_key, stream_messages


class JsonLines:
    """Every log line written while the fixture is active, parsed from JSON."""

    def __init__(self, stream: io.StringIO) -> None:
        self._stream = stream

    def all(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self._stream.getvalue().splitlines()]

    def with_id(self, correlation_id: str) -> list[dict[str, Any]]:
        return [line for line in self.all() if line.get("correlation_id") == correlation_id]


@pytest.fixture
def json_logs() -> Iterator[JsonLines]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(build_formatter("json"))
    root = logging.getLogger()
    saved_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    yield JsonLines(stream)
    root.removeHandler(handler)
    root.setLevel(saved_level)


async def test_every_response_carries_an_id_and_a_safe_incoming_one_is_kept(
    client: AsyncClient, json_logs: JsonLines
) -> None:
    fresh = await client.get("/")
    assert len(fresh.headers["X-Correlation-ID"]) == 32  # a new uuid4 hex

    kept = await client.get("/", headers={"X-Correlation-ID": "nginx-req-0001"})
    assert kept.headers["X-Correlation-ID"] == "nginx-req-0001"

    unsafe = await client.get("/", headers={"X-Correlation-ID": 'x", "admin": true'})
    assert unsafe.headers["X-Correlation-ID"] != 'x", "admin": true'

    [access] = json_logs.with_id("nginx-req-0001")  # one access line per request
    assert access["event"] == "request"
    assert access["logger"] == "app.access"
    assert (access["method"], access["path"], access["route"], access["status"]) == (
        "GET",
        "/",
        "/",
        200,
    )
    assert access["duration_ms"] >= 0


async def test_health_checks_are_not_access_logged(
    client: AsyncClient, json_logs: JsonLines
) -> None:
    await client.get("/health/live", headers={"X-Correlation-ID": "health-0001"})
    assert json_logs.with_id("health-0001") == []


async def test_a_purchase_is_traceable_from_the_request_to_the_worker(
    client: AsyncClient,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
    redis: Redis,
    db_engine: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
    json_logs: JsonLines,
) -> None:
    held = await hold(client, sale, user_id=buyers[0], quantity=2)
    confirm_id = "confirm-req-0001"
    confirmed = await client.post(
        f"/holds/{held.json()['hold_id']}/confirm",
        json={"payment_token": "tok_ok"},
        headers={**bearer(buyers[0]), "Idempotency-Key": new_key(), "X-Correlation-ID": confirm_id},
    )
    assert confirmed.status_code == 202

    # 1. The outbox row remembers which request wrote it.
    async with db_engine.connect() as conn:
        row_id, stored = (
            await conn.execute(text("SELECT id, correlation_id FROM outbox_events"))
        ).one()
    assert stored == confirm_id

    await run_pipeline(sessions, redis)

    # 2. The stream message carries it to the worker.
    [message] = await stream_messages(redis, ORDERS_STREAM_KEY)
    assert message["correlation_id"] == confirm_id

    # 3. The worker's log lines about this order carry it too.
    traced = json_logs.with_id(confirm_id)
    issued = [line for line in traced if "issued tickets" in line["event"]]
    assert issued and issued[0]["logger"] == "app.worker.handlers"
    assert issued[0]["outbox_id"] == str(row_id)
    # ...along with the confirm request's own access line.
    assert any(line["event"] == "request" and line["status"] == 202 for line in traced)


async def test_an_orm_row_gets_the_current_id_and_none_outside_a_request(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with sessions() as session, session.begin():
        outside = OutboxEvent(type="order.placed", aggregate_id="a", payload={})
        session.add(outside)
        # The default is read when the INSERT runs (at flush), not when the
        # object is created: so flush here, outside any scope.
        await session.flush()
        with correlation_scope("script-run-0001"):
            inside = OutboxEvent(type="order.placed", aggregate_id="b", payload={})
            session.add(inside)
            await session.flush()
    assert inside.correlation_id == "script-run-0001"
    assert outside.correlation_id is None


async def test_a_500_uses_the_request_id_in_body_header_and_logs(json_logs: JsonLines) -> None:
    async def broken_database() -> AsyncIterator[object]:
        raise RuntimeError("connection to db-internal-7 failed")
        yield  # pragma: no cover

    app.dependency_overrides[get_db_session] = broken_database
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as raw:
            response = await raw.get("/events", headers={"X-Correlation-ID": "broken-req-0001"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 500
    assert response.json()["correlation_id"] == "broken-req-0001"
    assert response.headers["X-Correlation-ID"] == "broken-req-0001"
    lines = json_logs.with_id("broken-req-0001")
    [error] = [line for line in lines if line["level"] == "error"]
    assert "RuntimeError: connection to db-internal-7 failed" in error["exception"]
    [access] = [line for line in lines if line["event"] == "request"]
    assert access["status"] == 500
