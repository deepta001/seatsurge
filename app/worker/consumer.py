"""The stream consumer: reads `stream:orders` as part of a consumer group and runs a handler.

Every worker process joins the group `order-workers`, so Redis gives each
message to exactly one of them. A message is acknowledged (XACK) only after
its handler finished without error. A PermanentError dead-letters it at
once; any other error leaves it pending, for `retries.py` to try again later.
"""

import logging
import os
import socket
from collections.abc import Mapping
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from app.core.job_errors import PermanentError
from app.redis.keys import ORDERS_STREAM_KEY
from app.worker.dead_letters import Compensation, dead_letter
from app.worker.messages import Handler, parse_message

logger = logging.getLogger(__name__)

ORDERS_GROUP = "order-workers"


def consumer_name() -> str:
    """Unique per process, so the pending list shows exactly which worker had a message."""
    return f"{socket.gethostname()}-{os.getpid()}"


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


async def handle_entry(
    redis: Redis,
    handlers: Mapping[str, Handler],
    compensations: Mapping[str, Compensation],
    *,
    entry_id: str,
    fields: Mapping[str, str],
    deliveries: int,
    stream: str = ORDERS_STREAM_KEY,
    group: str = ORDERS_GROUP,
) -> bool:
    """Handle one stream entry. True if the handler succeeded and it was acked.

    PermanentError: retrying can't help, so dead-letter it now. Any other
    error: leave it pending (not acked) to be retried after a delay.
    """
    try:
        message = parse_message(entry_id, fields)
        handler = handlers.get(message.type)
        if handler is None:
            raise PermanentError(f"no handler for message type {message.type!r}")
        await handler(message)
    except PermanentError as error:
        try:
            await dead_letter(
                redis,
                compensations,
                entry_id=entry_id,
                fields=fields,
                reason=f"{type(error).__name__}: {error}",
                deliveries=deliveries,
                stream=stream,
                group=group,
            )
        except Exception:
            # Still pending, so the retry pass will try dead-lettering again.
            logger.exception("consumer: could not dead-letter %s; left pending", entry_id)
        return False
    except Exception:
        # One bad message never stops the rest of the batch.
        logger.exception("consumer: message %s failed; left pending for a retry", entry_id)
        return False
    # Only now, with the handler's work done, is it safe to say "done".
    await redis.xack(stream, group, entry_id)
    return True


async def consume_batch(
    redis: Redis,
    handlers: Mapping[str, Handler],
    compensations: Mapping[str, Compensation] | None = None,
    *,
    consumer: str,
    count: int = 10,
    block_ms: int | None = 1000,
    stream: str = ORDERS_STREAM_KEY,
    group: str = ORDERS_GROUP,
) -> int:
    """Read up to `count` new messages and handle each. Returns how many succeeded.

    `block_ms` makes Redis wait that long for a message to arrive instead of
    us polling in a tight loop; None returns at once.
    """
    handled = 0
    for entry_id, fields in await read_new_entries(redis, consumer, count, block_ms, stream, group):
        if await handle_entry(
            redis,
            handlers,
            compensations or {},
            entry_id=entry_id,
            fields=fields,
            deliveries=1,  # ">" only ever hands out first deliveries
            stream=stream,
            group=group,
        ):
            handled += 1
    return handled
