"""Live availability (S7.3): change flags, the coalescing publisher, one shared
subscription per process, and the SSE stream over a real HTTP server."""

import asyncio
import json
import socket
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import uvicorn
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api.dependencies import get_live_updates
from app.api.live import QUEUE_SIZE, LiveUpdates
from app.main import app
from app.redis.keys import EVENTS_CHANGED_KEY, inventory_key, live_channel
from app.services.live_updates import availability_snapshot
from app.worker.live_publisher import publish_changes
from tests.sales import Sale, bearer, hold
from tests.seating import Venue, hold_seats


@pytest.fixture
async def live(redis: Redis) -> AsyncIterator[LiveUpdates]:
    """A started shared subscription, plugged into the app."""
    updates = LiveUpdates(redis)
    await updates.start()
    await asyncio.sleep(0.1)  # let it subscribe before anything is published
    app.dependency_overrides[get_live_updates] = lambda: updates
    yield updates
    await updates.stop()


@pytest.fixture
async def server(client: AsyncClient, live: LiveUpdates) -> AsyncIterator[str]:
    """The real app on a real port (in this event loop), using the test databases."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config = uvicorn.Config(app, host="127.0.0.1", port=port, lifespan="off", log_level="warning")
    real_server = uvicorn.Server(config)
    task = asyncio.create_task(real_server.serve())
    while not real_server.started:
        await asyncio.sleep(0.02)
    yield f"http://127.0.0.1:{port}"
    real_server.should_exit = True
    await task


async def next_event(lines: AsyncIterator[str]) -> dict[str, Any]:
    """Read SSE lines until one `data:` line arrives; return its JSON."""

    async def read() -> dict[str, Any]:
        async for line in lines:
            if line.startswith("data: "):
                parsed: dict[str, Any] = json.loads(line[len("data: ") :])
                return parsed
        raise AssertionError("stream ended")

    return await asyncio.wait_for(read(), timeout=5)


async def test_a_hold_is_flagged_and_published_as_one_fresh_snapshot(
    client: AsyncClient,
    sale: Sale,
    redis: Redis,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    listener = redis.pubsub()
    await listener.subscribe(live_channel(sale.event_id))
    await listener.get_message(timeout=1)  # the subscribe confirmation

    for user_id in range(1, 21):  # a burst of 20 holds...
        assert (await hold(client, sale, user_id=user_id, quantity=1)).status_code == 201
    assert await redis.smembers(EVENTS_CHANGED_KEY) == {str(sale.event_id)}

    assert await publish_changes(sessions, redis) == 1  # ...becomes ONE update

    message = await listener.get_message(timeout=2)
    assert message is not None
    assert json.loads(message["data"]) == {
        "event_id": sale.event_id,
        "tiers": [{"tier_id": sale.tier_id, "available": 30}],
    }
    assert await listener.get_message(timeout=0.3) is None  # nothing else was sent
    assert await publish_changes(sessions, redis) == 0  # no new changes, no message
    await listener.aclose()  # type: ignore[no-untyped-call]


async def test_a_missing_counter_is_left_out_never_guessed(
    sale: Sale, redis: Redis, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await redis.delete(inventory_key(sale.event_id, sale.tier_id))

    async with sessions() as session:
        snapshot = await availability_snapshot(session, redis, sale.event_id)

    assert snapshot == {"event_id": sale.event_id, "tiers": []}


async def test_a_reserved_event_announces_that_its_seat_map_changed(
    client: AsyncClient, venue: Venue, redis: Redis, sessions: async_sessionmaker[AsyncSession]
) -> None:
    assert (await hold_seats(client, venue, [venue.floor[0]])).status_code == 201

    async with sessions() as session:
        snapshot = await availability_snapshot(session, redis, venue.event_id)

    assert await redis.smembers(EVENTS_CHANGED_KEY) == {str(venue.event_id)}
    assert snapshot == {"event_id": venue.event_id, "seat_map_changed": True}


async def test_many_viewers_share_one_subscription_and_a_slow_one_only_loses_old_updates(
    live: LiveUpdates, redis: Redis
) -> None:
    async with (
        live.subscribe(7) as fast,
        live.subscribe(7) as slow,
        live.subscribe(8) as other_event,
    ):
        assert live.viewer_count(7) == 2
        for n in range(QUEUE_SIZE + 5):  # more than a queue holds
            await redis.publish(live_channel(7), json.dumps({"n": n}))
            got = await asyncio.wait_for(fast.get(), timeout=2)  # the fast viewer keeps up
            assert json.loads(got) == {"n": n}

        # The slow viewer never read: it kept the NEWEST updates, dropping the oldest.
        kept = [json.loads(slow.get_nowait())["n"] for _ in range(slow.qsize())]
        assert kept == list(range(5, QUEUE_SIZE + 5))
        assert other_event.empty()  # updates go only to that event's viewers
    assert live.viewer_count(7) == 0  # leaving the block unregisters the viewer


async def test_the_sse_stream_sends_the_current_state_then_each_update(
    server: str,
    client: AsyncClient,
    sale: Sale,
    redis: Redis,
    sessions: async_sessionmaker[AsyncSession],
    live: LiveUpdates,
    db_engine: AsyncEngine,
) -> None:
    async with (
        httpx.AsyncClient(base_url=server) as http,
        http.stream("GET", f"/events/{sale.event_id}/stream") as response,
    ):
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        lines = response.aiter_lines()
        first = await next_event(lines)
        assert first["tiers"] == [{"tier_id": sale.tier_id, "available": 50}]

        # The open stream holds no database connection (only the shared Redis one).
        assert db_engine.pool.checkedout() == 0  # type: ignore[attr-defined]

        await hold(client, sale, user_id=1, quantity=4)
        await publish_changes(sessions, redis)

        update = await next_event(lines)
        assert update["tiers"] == [{"tier_id": sale.tier_id, "available": 46}]


async def test_a_draft_or_unknown_event_has_no_stream(
    client: AsyncClient, live: LiveUpdates
) -> None:
    assert (await client.get("/events/999999/stream", headers=bearer(1))).status_code == 404
