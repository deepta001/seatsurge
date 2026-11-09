"""Makes a stream handler safe to run twice: the second delivery of a message does nothing.

Messages arrive at least once, so duplicates will happen (a relay crash
before marking PUBLISHED, a worker crash before XACK). `run_once` records
each message in `processed_messages` inside the SAME transaction as the
handler's own database work, so "it's done" and "the work" always commit
or roll back together.
"""

import logging
from collections.abc import Awaitable, Callable

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.outbox_models import ProcessedMessage
from app.worker.consumer import Handler, StreamMessage

logger = logging.getLogger(__name__)

# A handler that does its work with the session it's given (and never commits itself).
DbHandler = Callable[[AsyncSession, StreamMessage], Awaitable[None]]


async def claim_message(session: AsyncSession, message_id: int) -> bool:
    """Record the message as processed. True if this is the first time, False if a duplicate.

    ON CONFLICT DO NOTHING turns "already there" into "0 rows inserted"
    instead of an error. If another worker inserted the same id and hasn't
    committed yet, Postgres makes this INSERT wait for it: on its commit we
    see a duplicate, on its rollback we claim the message ourselves.
    """
    statement = (
        pg_insert(ProcessedMessage)
        .values(message_id=message_id)
        .on_conflict_do_nothing(index_elements=[ProcessedMessage.message_id])
        .returning(ProcessedMessage.message_id)
    )
    inserted = await session.scalar(statement)
    return inserted is not None


def run_once(
    session_factory: async_sessionmaker[AsyncSession],
    handler: DbHandler,
    *,
    after_commit: Handler | None = None,
) -> Handler:
    """Wrap a database handler so each outbox message is acted on exactly once.

    One transaction: claim the message id, then do the work. If the work
    fails, the claim rolls back with it, so a redelivery tries again. A
    duplicate returns normally, so the consumer acks it and it's gone.

    `after_commit` is for follow-up work outside Postgres (Redis), which must
    only happen once the commit succeeded (rule 6). It runs after the first
    processing AND for duplicates: if the worker crashed between the commit
    and this step, the redelivered duplicate finishes the job. So it must be
    idempotent itself.
    """

    async def handle(message: StreamMessage) -> None:
        async with session_factory() as session, session.begin():
            first_time = await claim_message(session, message.outbox_id)
            if first_time:
                await handler(session, message)
        # Leaving `begin()` committed the claim and the work together.
        if not first_time:
            logger.info(
                "consumer: outbox message %s already processed; skipping duplicate %s",
                message.outbox_id,
                message.entry_id,
            )
        if after_commit is not None:
            await after_commit(message)

    return handle
