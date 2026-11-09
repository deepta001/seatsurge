"""The outbox relay: copies committed outbox rows onto the `stream:orders` Redis Stream.

Confirm writes "issue these tickets" into `outbox_events` in the same
transaction as the order. This task picks up PENDING rows, publishes each one
with XADD, and marks it PUBLISHED. `FOR UPDATE SKIP LOCKED` lets several
relays run at once without waiting on, or double-publishing, each other's rows.
A row that keeps failing is retried with growing delays, then marked DEAD.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import timedelta

from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.correlation import correlation_scope
from app.core.job_errors import PermanentError
from app.db.outbox_models import OutboxEvent, OutboxStatus
from app.redis.keys import ORDERS_STREAM_KEY

logger = logging.getLogger(__name__)

BATCH_SIZE = 50
# Which stream each outbox event type goes to. An unknown type can never be
# published, so it is a PermanentError (DEAD at once), not something to retry.
STREAM_FOR_TYPE = {"order.placed": ORDERS_STREAM_KEY, "order.cancelled": ORDERS_STREAM_KEY}
# Long enough to hold the error's class and message, short enough for a column.
MAX_ERROR_LENGTH = 500


@dataclass(frozen=True)
class RetryPolicy:
    """How often a failing row is retried: 1 s, 2 s, 4 s ... capped, then DEAD."""

    max_attempts: int = 8
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 300.0

    def delay_after(self, attempts: int) -> float:
        """Exponential backoff: each failure doubles the wait, up to the cap."""
        return min(self.base_delay_seconds * 2.0 ** (attempts - 1), self.max_delay_seconds)


DEFAULT_POLICY = RetryPolicy()


def stream_fields(row: OutboxEvent) -> dict[str, str]:
    """A stream entry is a flat map of strings, so the JSON payload is sent as text.

    `outbox_id` travels with the message: if a row is ever published twice
    (see `relay_batch`), both copies carry the same id, so the consumer can
    recognise the duplicate even though Redis gives each copy a new entry id.
    """
    fields = {
        "outbox_id": str(row.id),
        "type": row.type,
        "aggregate_id": row.aggregate_id,
        "payload": json.dumps(row.payload),
    }
    if row.correlation_id is not None:
        # The request's id rides along, so the worker's log lines carry it too.
        fields["correlation_id"] = row.correlation_id
    return fields


async def publish(redis: Redis, row: OutboxEvent) -> None:
    stream = STREAM_FOR_TYPE.get(row.type)
    if stream is None:
        raise PermanentError(f"no stream for outbox event type {row.type!r}")
    await redis.xadd(stream, stream_fields(row))  # type: ignore[arg-type]


def describe(error: Exception) -> str:
    return f"{type(error).__name__}: {error}"[:MAX_ERROR_LENGTH]


def mark_dead(row: OutboxEvent, error: Exception) -> None:
    row.status = OutboxStatus.DEAD
    row.last_error = describe(error)
    # The "alert": an ERROR log for now; a metric joins it in S8.2.
    logger.error(
        "relay: outbox row %s is DEAD after %d attempt(s): %s", row.id, row.attempts, row.last_error
    )


def record_failure(row: OutboxEvent, error: Exception, policy: RetryPolicy) -> None:
    """Count the failed attempt, then either schedule a retry or give up."""
    row.attempts += 1
    if isinstance(error, PermanentError) or row.attempts >= policy.max_attempts:
        mark_dead(row, error)
        return
    row.last_error = describe(error)
    # The database's clock, not this machine's: several workers on different
    # machines then agree on when a row is due.
    row.next_retry_at = func.now() + timedelta(seconds=policy.delay_after(row.attempts))
    logger.warning(
        "relay: outbox row %s failed (attempt %d): %s", row.id, row.attempts, row.last_error
    )


async def relay_batch(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    *,
    batch_size: int = BATCH_SIZE,
    policy: RetryPolicy = DEFAULT_POLICY,
) -> int:
    """Publish up to `batch_size` due PENDING rows, oldest first. Returns how many.

    Order of work: XADD each row, then commit "PUBLISHED" for the batch. If
    the process dies between the two, the rows are still PENDING and get
    published again later: a duplicate, never a loss (at-least-once). The
    consumer de-duplicates by `outbox_id` (S4.4).
    """
    async with session_factory() as session, session.begin():
        query = (
            select(OutboxEvent)
            .where(
                OutboxEvent.status == OutboxStatus.PENDING,
                OutboxEvent.next_retry_at <= func.now(),
            )
            .order_by(OutboxEvent.id)
            .limit(batch_size)
            # Lock the rows we take; another relay skips them instead of
            # waiting, and takes the next unlocked ones.
            .with_for_update(skip_locked=True)
        )
        rows = (await session.scalars(query)).all()

        published = 0
        for row in rows:
            # Log lines about this row carry the id of the request that wrote it.
            with correlation_scope(row.correlation_id, outbox_id=row.id):
                try:
                    await publish(redis, row)
                except (RedisConnectionError, RedisTimeoutError):
                    # Redis itself is unreachable: not this row's fault, so no
                    # attempt is counted (otherwise an outage would kill every
                    # row). Stop the batch; the loop tries again shortly.
                    logger.warning("relay: Redis unreachable; stopping this batch")
                    break
                except Exception as error:
                    # This row's own problem. It never blocks the rows behind it.
                    record_failure(row, error, policy)
                    continue
                row.status = OutboxStatus.PUBLISHED
                row.published_at = func.now()
                published += 1
        # Leaving the `begin()` block commits, which also releases the row locks.
    return published


async def delete_old_published(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    older_than: timedelta,
    limit: int = 1000,
) -> int:
    """Delete up to `limit` PUBLISHED rows older than `older_than`. Returns how many.

    Published rows have done their job; keeping them forever would only slow
    the table down. PENDING and DEAD rows are never deleted here. A limit
    keeps each delete short, so it never holds many locks for long.
    """
    oldest_allowed = func.now() - older_than
    doomed = (
        select(OutboxEvent.id)
        .where(
            OutboxEvent.status == OutboxStatus.PUBLISHED, OutboxEvent.published_at < oldest_allowed
        )
        .limit(limit)
    )
    async with session_factory() as session, session.begin():
        result = await session.execute(delete(OutboxEvent).where(OutboxEvent.id.in_(doomed)))
    return int(result.rowcount)  # type: ignore[attr-defined]


async def run_relay(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    *,
    idle_seconds: float = 0.5,
    keep_published: timedelta = timedelta(hours=24),
    cleanup_every_seconds: float = 60.0,
) -> None:
    """Relay forever. A full batch means more may be waiting, so go again at once."""
    logger.info("relay started")
    next_cleanup = time.monotonic()
    while True:
        try:
            published = await relay_batch(session_factory, redis)
        except Exception:
            # Postgres briefly down: log it and try again next tick.
            logger.exception("relay: pass failed; retrying next tick")
            published = 0
        if published:
            logger.info("relay: published %d outbox row(s)", published)

        if time.monotonic() >= next_cleanup:
            next_cleanup = time.monotonic() + cleanup_every_seconds
            try:
                deleted = await delete_old_published(session_factory, older_than=keep_published)
                if deleted:
                    logger.info("relay: deleted %d old published row(s)", deleted)
            except Exception:
                logger.exception("relay: cleanup failed; retrying later")

        if published < BATCH_SIZE:
            await asyncio.sleep(idle_seconds)
