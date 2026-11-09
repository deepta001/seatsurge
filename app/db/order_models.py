"""Table models for buying: orders and the tickets they produce (CLAUDE.md section 6).

The partial unique indexes on tickets are the last line of defence against
double-selling: even if Redis and the app both got it wrong, Postgres refuses
a second ISSUED ticket for the same seat or the same ticket number.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models import status_column_type


class OrderStatus(enum.StrEnum):
    PENDING = "PENDING"  # confirmed by the user, tickets not issued yet (worker, Phase C)
    CONFIRMED = "CONFIRMED"  # tickets issued
    FAILED = "FAILED"  # could not be fulfilled; inventory released
    CANCELLED = "CANCELLED"  # cancelled after confirmation (S5.3)


class TicketStatus(enum.StrEnum):
    ISSUED = "ISSUED"
    CANCELLED = "CANCELLED"


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        # A retried confirm with the same Idempotency-Key finds the first order.
        UniqueConstraint("user_id", "idempotency_key"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("total_cents >= 0", name="total_not_negative"),
        # "Seats in PENDING orders" per tier, for the rebuild formula (S2.8).
        Index("ix_orders_tier_id_status", "tier_id", "status"),
    )

    # A random UUID, not 1, 2, 3...: order ids appear in URLs, and sequential
    # ids would reveal how many orders exist and invite guessing others' ids.
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"))
    # Not in the original CLAUDE.md schema: needed for the per-user purchase cap
    # and for counting pending seats per tier (docs/design.md, S3.1).
    tier_id: Mapped[int] = mapped_column(ForeignKey("tiers.id"))
    quantity: Mapped[int]
    # One hold can become at most one order, however often confirm is called.
    hold_id: Mapped[str] = mapped_column(String(64), unique=True)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    status: Mapped[OrderStatus] = mapped_column(
        status_column_type(OrderStatus, "order_status"),
        default=OrderStatus.PENDING,
        server_default=OrderStatus.PENDING.value,
    )
    total_cents: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = (
        CheckConstraint("ticket_number > 0", name="ticket_number_positive"),
        # The double-sell backstops. "Partial": only ISSUED tickets count, so a
        # cancelled ticket's seat can be sold again.
        Index(
            "uq_tickets_issued_seat",
            "event_id",
            "seat_id",
            unique=True,
            postgresql_where=text("status = 'ISSUED'"),
        ),
        Index(
            "uq_tickets_issued_number",
            "tier_id",
            "ticket_number",
            unique=True,
            postgresql_where=text("status = 'ISSUED'"),
        ),
        Index("ix_tickets_event_id_status", "event_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), index=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"))
    tier_id: Mapped[int] = mapped_column(ForeignKey("tiers.id"))
    # Reserved seating only (Phase D adds the seats table and its foreign key).
    seat_id: Mapped[int | None]
    ticket_number: Mapped[int]
    status: Mapped[TicketStatus] = mapped_column(
        status_column_type(TicketStatus, "ticket_status"),
        default=TicketStatus.ISSUED,
        server_default=TicketStatus.ISSUED.value,
    )
