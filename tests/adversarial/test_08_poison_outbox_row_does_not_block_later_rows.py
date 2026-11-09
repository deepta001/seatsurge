"""Adversarial test 8: a poison outbox row never blocks later rows; it ends DEAD with last_error.

Two kinds of poison: a row that can never be published (an unknown event
type: PermanentError, DEAD at once) and a row whose publish keeps failing
(retried with backoff, then DEAD after the last attempt).
"""

from typing import Any

import pytest
from redis.asyncio import Redis
from redis.exceptions import ResponseError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.worker.relay import RetryPolicy, relay_batch
from tests.outbox import add_rows, outbox_row, published_ids

# No waiting between retries, so the test can run every attempt straight away.
NO_DELAY = RetryPolicy(max_attempts=3, base_delay_seconds=0)


async def test_an_unpublishable_row_goes_dead_at_once_and_later_rows_still_go_out(
    sessions: async_sessionmaker[AsyncSession], db_engine: AsyncEngine, redis: Redis
) -> None:
    [poison] = await add_rows(db_engine, 1, event_type="order.mystery")
    good = await add_rows(db_engine, 3)

    assert await relay_batch(sessions, redis) == 3

    assert await published_ids(redis) == good
    row = await outbox_row(db_engine, poison)
    assert (row.status, row.attempts) == ("DEAD", 1)
    assert "PermanentError" in row.last_error
    assert "order.mystery" in row.last_error
    # DEAD is final: later passes leave it alone.
    assert await relay_batch(sessions, redis) == 0
    assert (await outbox_row(db_engine, poison)).attempts == 1


async def test_a_row_that_keeps_failing_is_retried_then_goes_dead(
    sessions: async_sessionmaker[AsyncSession],
    db_engine: AsyncEngine,
    redis: Redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    [poison] = await add_rows(db_engine, 1)
    real_xadd = redis.xadd

    async def xadd_failing_for_poison(name: str, fields: dict[str, str], **kwargs: Any) -> Any:
        if fields["outbox_id"] == str(poison):
            raise ResponseError("simulated: this message is rejected")
        return await real_xadd(name, fields, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(redis, "xadd", xadd_failing_for_poison)

    # Attempts 1 and 2 fail but leave it PENDING for another try.
    for attempt in (1, 2):
        later = await add_rows(db_engine, 1)  # a new order arrives behind the poison row
        assert await relay_batch(sessions, redis, policy=NO_DELAY) == 1
        assert (await published_ids(redis))[-1] == later[0]
        row = await outbox_row(db_engine, poison)
        assert (row.status, row.attempts) == ("PENDING", attempt)
        assert row.last_error == "ResponseError: simulated: this message is rejected"

    # The last allowed attempt fails: it gives up.
    assert await relay_batch(sessions, redis, policy=NO_DELAY) == 0
    row = await outbox_row(db_engine, poison)
    assert (row.status, row.attempts) == ("DEAD", 3)
    assert poison not in await published_ids(redis)
