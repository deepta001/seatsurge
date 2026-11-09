"""The consumer reads `stream:orders` through a consumer group (real Redis; Postgres for e2e)."""

import asyncio
import json
from typing import Any

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.redis.keys import DEAD_LETTER_STREAM_KEY, ORDERS_STREAM_KEY
from app.worker.consumer import ORDERS_GROUP, consume_batch, ensure_group
from app.worker.messages import StreamMessage
from app.worker.relay import relay_batch
from tests.outbox import add_rows
from tests.sales import stream_messages


class Recorder:
    """A handler that remembers what it was given, and can be told to fail for some messages."""

    def __init__(self, fail_for: set[int] | None = None) -> None:
        self.seen: list[StreamMessage] = []
        self.fail_for = fail_for or set()

    async def __call__(self, message: StreamMessage) -> None:
        if message.outbox_id in self.fail_for:
            raise RuntimeError("simulated handler failure")
        self.seen.append(message)


async def publish(redis: Redis, outbox_id: int, event_type: str = "order.placed") -> str:
    fields = {
        "outbox_id": str(outbox_id),
        "type": event_type,
        "aggregate_id": f"order-{outbox_id}",
        "payload": json.dumps({"n": outbox_id}),
    }
    return str(await redis.xadd(ORDERS_STREAM_KEY, fields))  # type: ignore[arg-type]


async def pending(redis: Redis) -> dict[str, Any]:
    summary: dict[str, Any] = await redis.xpending(ORDERS_STREAM_KEY, ORDERS_GROUP)
    return {str(c["name"]): int(c["pending"]) for c in summary["consumers"]}


async def test_ensure_group_creates_the_stream_and_is_safe_to_repeat(redis: Redis) -> None:
    await ensure_group(redis)
    await asyncio.gather(*(ensure_group(redis) for _ in range(5)))  # many workers starting

    groups = await redis.xinfo_groups(ORDERS_STREAM_KEY)
    assert [str(g["name"]) for g in groups] == [ORDERS_GROUP]


async def test_messages_published_before_the_group_existed_are_still_delivered(
    redis: Redis,
) -> None:
    await publish(redis, 1)
    await publish(redis, 2)
    await ensure_group(redis)
    handler = Recorder()

    assert await consume_batch(redis, {"order.placed": handler}, consumer="w1", block_ms=None) == 2

    assert [m.outbox_id for m in handler.seen] == [1, 2]
    assert handler.seen[0].payload == {"n": 1}
    assert await pending(redis) == {}  # both acked


async def test_a_failed_message_is_left_pending_and_the_rest_are_acked(redis: Redis) -> None:
    await ensure_group(redis)
    for outbox_id in (1, 2, 3):
        await publish(redis, outbox_id)
    handler = Recorder(fail_for={2})

    assert await consume_batch(redis, {"order.placed": handler}, consumer="w1", block_ms=None) == 2

    assert [m.outbox_id for m in handler.seen] == [1, 3]
    assert await pending(redis) == {"w1": 1}
    # ">" only hands out never-delivered messages: the failed one waits for a retry pass.
    assert await consume_batch(redis, {"order.placed": handler}, consumer="w1", block_ms=None) == 0


async def test_unknown_types_and_malformed_messages_go_to_the_dead_letter_stream(
    redis: Redis,
) -> None:
    await ensure_group(redis)
    await publish(redis, 1, event_type="order.mystery")
    await redis.xadd(ORDERS_STREAM_KEY, {"garbage": "yes"})
    await publish(redis, 3)
    handler = Recorder()

    assert await consume_batch(redis, {"order.placed": handler}, consumer="w1", block_ms=None) == 1

    assert [m.outbox_id for m in handler.seen] == [3]
    # Retrying can never fix these (PermanentError), so they're set aside at once...
    dead = await stream_messages(redis, DEAD_LETTER_STREAM_KEY)
    assert [d["dead_reason"].split(":")[0] for d in dead] == ["PermanentError", "PermanentError"]
    assert "order.mystery" in dead[0]["dead_reason"]
    assert dead[1]["garbage"] == "yes"  # the original fields are kept for a human
    # ...and acked, so they don't sit in the pending list forever.
    assert await pending(redis) == {}


async def test_consumers_in_one_group_share_the_messages_without_overlap(redis: Redis) -> None:
    await ensure_group(redis)
    for outbox_id in range(1, 101):
        await publish(redis, outbox_id)
    start = asyncio.Event()
    handlers = {name: Recorder() for name in ("w1", "w2", "w3")}

    async def worker(name: str) -> None:
        await start.wait()  # all consumers begin together
        while await consume_batch(
            redis, {"order.placed": handlers[name]}, consumer=name, count=5, block_ms=None
        ):
            await asyncio.sleep(0)  # let the other consumers take turns

    tasks = [asyncio.create_task(worker(name)) for name in handlers]
    start.set()
    await asyncio.gather(*tasks)

    seen = [m.outbox_id for h in handlers.values() for m in h.seen]
    assert sorted(seen) == list(range(1, 101))  # every message once, none twice
    assert all(h.seen for h in handlers.values())  # the work really was shared
    assert await pending(redis) == {}


async def test_a_blocking_read_wakes_up_when_a_message_arrives(redis: Redis) -> None:
    await ensure_group(redis)
    handler = Recorder()
    reader = asyncio.create_task(
        consume_batch(redis, {"order.placed": handler}, consumer="w1", block_ms=5000)
    )
    await asyncio.sleep(0.2)  # the reader is now waiting inside Redis
    await publish(redis, 1)

    assert await asyncio.wait_for(reader, timeout=2) == 1


async def test_relay_to_consumer_end_to_end(
    sessions: async_sessionmaker[AsyncSession], db_engine: AsyncEngine, redis: Redis
) -> None:
    [row_id] = await add_rows(db_engine, 1)
    await ensure_group(redis)
    await relay_batch(sessions, redis)
    handler = Recorder()

    assert await consume_batch(redis, {"order.placed": handler}, consumer="w1", block_ms=None) == 1

    [message] = handler.seen
    assert (message.outbox_id, message.type, message.payload) == (row_id, "order.placed", {"n": 0})
