"""The outbox table: "work to do after this commit", written in the same transaction.

Confirming an order writes the order AND an outbox row together, so they
either both exist or neither does. A relay (S4.1) later reads PENDING rows
and publishes them to a Redis Stream for the worker. This is the "outbox
pattern": it never loses the follow-up work, even if the process crashes
right after committing.
"""

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.correlation import current_correlation_id
from app.db.base import Base
from app.db.models import status_column_type


class OutboxStatus(enum.StrEnum):
    PENDING = "PENDING"  # not yet published
    PUBLISHED = "PUBLISHED"  # handed to the Redis Stream
    DEAD = "DEAD"  # gave up after too many failures (S4.2)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        # The relay only ever looks for PENDING rows that are due: a small,
        # fast index that ignores the (much larger) published history.
        Index(
            "ix_outbox_events_pending_due",
            "next_retry_at",
            postgresql_where=text("status = 'PENDING'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # What happened, e.g. "order.placed".
    type: Mapped[str] = mapped_column(String(50))
    # Which thing it's about, e.g. the order id.
    aggregate_id: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # The id of the request that wrote this row (S8.2b), so the relay's and
    # worker's log lines about it can be matched to that request. Filled in
    # automatically: the default is read when the row is inserted, inside the
    # request. NULL for rows written outside one (older rows, scripts).
    correlation_id: Mapped[str | None] = mapped_column(String(64), default=current_correlation_id)
    status: Mapped[OutboxStatus] = mapped_column(
        status_column_type(OutboxStatus, "outbox_status"),
        default=OutboxStatus.PENDING,
        server_default=OutboxStatus.PENDING.value,
    )
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    next_retry_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProcessedMessage(Base):
    """One row per outbox message the worker has finished handling (CLAUDE.md section 6).

    Written in the SAME transaction as the handler's work, so "done" and
    "the work" commit or roll back together. A second delivery of the same
    message finds the row and is skipped.
    """

    __tablename__ = "processed_messages"

    # The outbox row id, not Redis's stream entry id: if the relay publishes
    # a row twice, each copy gets a new entry id but keeps the same outbox id.
    message_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
