"""The stream consumer: reads `stream:orders` as part of a consumer group and runs a handler.

Every worker process joins the group `order-workers`, so Redis gives each
message to exactly one of them. A message is acknowledged (XACK) only after
its handler finished without error; anything else stays in the group's
pending list, where S4.6 will retry it or dead-letter it.
"""

import asyncio
import json
import logging
import os
import socket
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from app.core.job_errors import PermanentError
from app.redis.keys import ORDERS_STREAM_KEY

logger = logging.getLogger(__name__)

ORDERS_GROUP = "order-workers"


@dataclass(frozen=True)
class StreamMessage:
    """One outbox event as read from the stream, with its fields checked and parsed."""

    entry_id: str  # Redis's id for this copy of the message
    outbox_id: int  # the outbox row it came from (the same for duplicates)
    type: str
    aggregate_id: str
    payload: dict[str, Any]


Handler = Callable[[StreamMessage], Awaitable[None]]


def consumer_name() -> str:
    """Unique per process, so the pending list shows exactly which worker had a message."""
    return f"{socket.gethostname()}-{os.getpid()}"


def parse_message(entry_id: str, fields: Mapping[str, str]) -> StreamMessage:
    """Turn raw stream fields into a StreamMessage. Bad data can never become good: permanent."""
    try:
        payload = json.loads(fields["payload"])
        if not isinstance(payload, dict):
            raise ValueError("payload is not a JSON object")
        return StreamMessage(
            entry_id=entry_id,
            outbox_id=int(fields["outbox_id"]),
            type=fields["type"],
            aggregate_id=fields["aggregate_id"],
            payload=payload,
        )
    except (KeyError, ValueError) as error:  # json.JSONDecodeError is a ValueError
        raise PermanentError(f"malformed stream message {entry_id}: {error!r}") from error


async def group_exists(redis: Redis, stream: str, group: str) -> bool:
    groups = await redis.xinfo_groups(stream)
    return any(str(info["name"]) == group for info in groups)


async def ensure_group(
    redis: Redis, stream: str = ORDERS_STREAM_KEY, group: str = ORDERS_GROUP
) -> None:
    """Create the consumer group if it's missing. Safe to call from every worker at startup.

    id="0": start from the first entry ever written, so messages the relay
    published before any worker existed are still processed. MKSTREAM
    creates the stream itself if nothing has been published yet.
    """
    try:
        await redis.xgroup_create(stream, group, id="0", mkstream=True)
    except ResponseError:
        # Another worker created it first (Redis says BUSYGROUP). Check the
        # fact itself rather than matching on the error's text (rule 9).
        if not await group_exists(redis, stream, group):
            raise


async def read_new_entries(
    redis: Redis, consumer: str, count: int, block_ms: int | None, stream: str, group: str
) -> list[tuple[str, dict[str, str]]]:
    """XREADGROUP with ">" (never-delivered entries only), as plain (entry_id, fields) pairs."""
    # The reply looks like [[stream_name, [(entry_id, {field: value}), ...]]],
    # or None when nothing arrived before the block timeout.
    response: Any = await redis.xreadgroup(
        group, consumer, {stream: ">"}, count=count, block=block_ms
    )
    entries: list[tuple[str, dict[str, str]]] = []
    for _stream_name, stream_entries in response or []:
        for entry_id, fields in stream_entries:
            entries.append((str(entry_id), {str(k): str(v) for k, v in fields.items()}))
    return entries


async def consume_batch(
    redis: Redis,
    handlers: Mapping[str, Handler],
    *,
    consumer: str,
    count: int = 10,
    block_ms: int | None = 1000,
    stream: str = ORDERS_STREAM_KEY,
    group: str = ORDERS_GROUP,
) -> int:
    """Read up to `count` new messages, handle each, and ack the successful ones. Returns how many.

    `block_ms` makes Redis wait that long for a message to arrive instead of
    us polling in a tight loop; None returns at once.
    """
    acked = 0
    for entry_id, fields in await read_new_entries(redis, consumer, count, block_ms, stream, group):
        try:
            message = parse_message(entry_id, fields)
            handler = handlers.get(message.type)
            if handler is None:
                raise PermanentError(f"no handler for message type {message.type!r}")
            await handler(message)
        except Exception:
            # Not acked: it stays in the pending list for S4.6 to retry or
            # dead-letter. One bad message never stops the rest of the batch.
            logger.exception("consumer: message %s failed; left pending", entry_id)
            continue
        # Only now, with the handler's work done, is it safe to say "done".
        await redis.xack(stream, group, entry_id)
        acked += 1
    return acked


async def run_consumer(redis: Redis, handlers: Mapping[str, Handler]) -> None:
    """Consume forever. A failed pass (Redis briefly down) is logged and retried."""
    name = consumer_name()
    logger.info("consumer %s started", name)
    group_ready = False
    while True:
        try:
            if not group_ready:
                await ensure_group(redis)
                group_ready = True
            handled = await consume_batch(redis, handlers, consumer=name)
            if handled:
                logger.info("consumer: handled %d message(s)", handled)
        except Exception:
            logger.exception("consumer: pass failed; retrying shortly")
            await asyncio.sleep(1)
