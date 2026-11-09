"""Metrics (S8.2): each number moves exactly when the thing it counts happens.

Counters are process-wide and only go up, so every test reads a value
before and after and checks the DIFFERENCE.
"""

import time

import pytest
from httpx import AsyncClient
from prometheus_client import REGISTRY
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.redis.keys import ORDERS_STREAM_KEY
from app.services.payments import MockPaymentProvider
from app.worker import handlers as handlers_module
from app.worker.backlog import refresh_outbox_gauges, refresh_stream_gauges
from app.worker.consumer import ORDERS_GROUP, ensure_group, read_new_entries
from app.worker.relay import relay_batch
from app.worker.sweeper import sweep_expired_holds
from tests.adversarial.test_09_failing_worker_dead_letters_and_releases_seats import (
    FAST,
    FlakyIssuer,
    place_order,
    retry_until_settled,
)
from tests.outbox import run_pipeline
from tests.sales import Sale, hold, new_key, stream_messages


def value(name: str, **labels: str) -> float:
    """The current value of one series (0 if it hasn't been recorded yet)."""
    return REGISTRY.get_sample_value(name, labels) or 0.0


async def test_metrics_page_lists_the_metrics(client: AsyncClient) -> None:
    response = await client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    for name in ("holds_created_total", "invariant_violations_total", "outbox_pending"):
        assert name in response.text


async def test_holds_are_counted_by_outcome_and_timed_by_route_template(
    client: AsyncClient, sale: Sale
) -> None:
    route = {"method": "POST", "route": "/events/{event_id}/holds"}
    created = value("holds_created_total")
    sold_out = value("holds_rejected_total", reason="sold_out")
    timed_201 = value("http_request_duration_seconds_count", **route, status="201")
    script = value("redis_script_duration_seconds_count", script="reserve_tier")

    key = new_key()
    assert (await hold(client, sale, user_id=1, quantity=2, key=key)).status_code == 201
    assert (await hold(client, sale, user_id=1, quantity=2, key=key)).status_code == 201  # replay
    for user_id in range(2, 7):
        assert (await hold(client, sale, user_id=user_id, quantity=10)).status_code in (201, 409)

    # 1 + 4 of the 10-seat holds fit (2 + 40 = 42 of 50); the 5th is sold out.
    assert value("holds_created_total") - created == 5  # the replay isn't a new hold
    assert value("holds_rejected_total", reason="sold_out") - sold_out == 1
    # One series per route TEMPLATE, never per event id; the replay is timed too.
    assert value("http_request_duration_seconds_count", **route, status="201") - timed_201 == 6
    assert value("redis_script_duration_seconds_count", script="reserve_tier") - script >= 6


async def test_rate_limited_holds_are_counted_as_rejected(
    client: AsyncClient, sale: Sale, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.settings import get_settings

    monkeypatch.setattr(get_settings(), "rate_limit_holds", 1)
    before = value("holds_rejected_total", reason="rate_limited")
    await hold(client, sale, user_id=9)
    assert (await hold(client, sale, user_id=9)).status_code == 429
    assert value("holds_rejected_total", reason="rate_limited") - before == 1


async def test_an_order_is_counted_confirmed_once_even_if_its_message_comes_twice(
    client: AsyncClient,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
    redis: Redis,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    placed, confirmed = value("orders_placed_total"), value("orders_confirmed_total")
    await place_order(client, sale, buyers[0], quantity=2)
    assert value("orders_placed_total") - placed == 1

    assert await run_pipeline(sessions, redis) == 1
    # Deliver the same entry again, as a crashed worker's redelivery would.
    [fields] = await stream_messages(redis, ORDERS_STREAM_KEY)
    await redis.xadd(ORDERS_STREAM_KEY, fields)  # type: ignore[arg-type]  # redis-py's dict hint
    assert await run_pipeline(sessions, redis) == 1  # acked as a harmless duplicate

    assert value("orders_confirmed_total") - confirmed == 1


async def test_a_dead_lettered_order_counts_as_failed_and_dead_lettered(
    client: AsyncClient,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
    redis: Redis,
    sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed = value("orders_failed_total")
    dead = value("dead_letters_total", type="order.placed")
    confirmed = value("orders_confirmed_total")
    await place_order(client, sale, buyers[0], quantity=1)
    monkeypatch.setattr(handlers_module, "issue_tickets", FlakyIssuer(failures=99))

    await run_pipeline(sessions, redis)
    await retry_until_settled(sessions, redis, FAST)

    assert value("orders_failed_total") - failed == 1
    assert value("dead_letters_total", type="order.placed") - dead == 1
    assert value("orders_confirmed_total") == confirmed  # a rolled-back attempt never counts


async def test_backlog_gauges_show_waiting_outbox_rows_and_unacked_messages(
    client: AsyncClient,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
    redis: Redis,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await place_order(client, sale, buyers[0], quantity=1)
    await place_order(client, sale, buyers[1], quantity=1)
    await refresh_outbox_gauges(sessions)
    await refresh_stream_gauges(redis)
    assert value("outbox_pending") == 2
    assert value("outbox_oldest_pending_age_seconds") >= 0
    assert value("stream_pending_messages") == 0

    # Published, and read by a worker that hasn't acked yet (say, it's mid-work).
    await relay_batch(sessions, redis)
    await ensure_group(redis)
    await read_new_entries(redis, "slow-worker", 10, None, ORDERS_STREAM_KEY, ORDERS_GROUP)
    await refresh_outbox_gauges(sessions)
    await refresh_stream_gauges(redis)
    assert value("outbox_pending") == 0
    assert value("outbox_oldest_pending_age_seconds") == 0
    assert value("stream_pending_messages") == 2


async def test_swept_holds_are_counted_as_expiries(
    client: AsyncClient, sale: Sale, redis: Redis, db_engine: AsyncEngine
) -> None:
    before = value("hold_expiries_total")
    assert (await hold(client, sale, user_id=1, quantity=1)).status_code == 201
    assert (await hold(client, sale, user_id=2, quantity=1)).status_code == 201

    far_future_ms = int((time.time() + 3600) * 1000)
    assert await sweep_expired_holds(redis, now=far_future_ms) == 2
    assert value("hold_expiries_total") - before == 2
