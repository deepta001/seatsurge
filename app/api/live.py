"""Live availability over Server-Sent Events: GET /events/{event_id}/stream (S7.3).

Each API process keeps ONE Redis subscription (to every `chan:event:*`
channel) and hands each message to the in-memory queues of the viewers
watching that event. A viewer never holds a Redis connection of its own, so
thousands of open pages can't use up the pool that holds and confirms need.
Because the worker PUBLISHes through Redis, viewers on any replica get every
update.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.dependencies import get_live_updates, get_redis, get_session_factory
from app.services.events import get_public_event
from app.services.live_updates import availability_snapshot

logger = logging.getLogger(__name__)
router = APIRouter(tags=["events"])

CHANNEL_PATTERN = "chan:event:*"
HEARTBEAT_SECONDS = 15.0  # a comment line now and then keeps proxies from closing idle streams
QUEUE_SIZE = 20


def offer(queue: "asyncio.Queue[str]", data: str) -> None:
    """Add without ever waiting: a viewer that falls behind loses its OLDEST update.

    Every update is a full snapshot, so the newest one is all a viewer needs;
    one slow connection must never hold up everyone else.
    """
    if queue.full():
        queue.get_nowait()
    queue.put_nowait(data)


class LiveUpdates:
    """One shared Redis subscription per process, fanned out to viewer queues."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._viewers: dict[int, set[asyncio.Queue[str]]] = {}
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._pump())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def viewer_count(self, event_id: int) -> int:
        return len(self._viewers.get(event_id, ()))

    @asynccontextmanager
    async def subscribe(self, event_id: int) -> AsyncIterator["asyncio.Queue[str]"]:
        """A queue receiving this event's updates until the `with` block ends."""
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._viewers.setdefault(event_id, set()).add(queue)
        try:
            yield queue
        finally:
            viewers = self._viewers.get(event_id, set())
            viewers.discard(queue)
            if not viewers:
                self._viewers.pop(event_id, None)

    async def _pump(self) -> None:
        """Read the shared subscription forever; reconnect after a Redis outage."""
        while True:
            pubsub = self._redis.pubsub()
            try:
                await pubsub.psubscribe(CHANNEL_PATTERN)
                async for message in pubsub.listen():
                    if message["type"] == "pmessage":
                        self._deliver(str(message["channel"]), str(message["data"]))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("live updates: subscription lost; reconnecting")
                await asyncio.sleep(1)
            finally:
                await pubsub.aclose()  # type: ignore[no-untyped-call]  # redis-py lacks a hint

    def _deliver(self, channel: str, data: str) -> None:
        event_id = int(channel.rsplit(":", 1)[1])
        for queue in list(self._viewers.get(event_id, ())):
            offer(queue, data)


def sse(data: str) -> str:
    """One Server-Sent Event: `data:` lines ended by a blank line."""
    return f"event: availability\ndata: {data}\n\n"


async def event_stream(
    live: LiveUpdates,
    event_id: int,
    first: dict[str, Any],
    request: Request,
    heartbeat_seconds: float = HEARTBEAT_SECONDS,
) -> AsyncIterator[str]:
    """The current snapshot, then every update, until the viewer goes away."""
    async with live.subscribe(event_id) as queue:
        yield sse(json.dumps(first))
        while not await request.is_disconnected():
            try:
                data = await asyncio.wait_for(queue.get(), timeout=heartbeat_seconds)
            except TimeoutError:
                yield ": keep-alive\n\n"
                continue
            yield sse(data)


@router.get("/events/{event_id}/stream")
async def stream_availability(
    event_id: int,
    request: Request,
    sessions: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
    redis: Redis = Depends(get_redis),
    live: LiveUpdates = Depends(get_live_updates),
) -> StreamingResponse:
    """Live availability for a published event (Server-Sent Events). Drafts are 404.

    Sends the current state at once, then at most 5 updates a second while
    things change, and a keep-alive comment every 15 s. Works on any replica.
    """
    # A short session, closed BEFORE streaming starts. A `Depends(get_db_session)`
    # would stay open as long as the viewer watches (FastAPI keeps dependencies
    # until the response ends), so ~15 viewers would use up the database pool.
    async with sessions() as session:
        await get_public_event(session, event_id)
        first = await availability_snapshot(session, redis, event_id) or {"event_id": event_id}
    return StreamingResponse(
        event_stream(live, event_id, first, request),
        media_type="text/event-stream",
        # no-cache: never stored; X-Accel-Buffering: tells nginx (S8.1) to pass
        # each event through at once instead of buffering the stream.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
