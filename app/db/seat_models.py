"""Seats for reserved-seating events: one row per physical seat (CLAUDE.md section 6).

Seats are created together with a RESERVED event (one per unit of each
tier's capacity). A ticket for a specific seat points at its row, and the
partial unique index on tickets (event_id, seat_id) WHERE ISSUED makes sure
one seat can never have two live tickets.
"""

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Seat(Base):
    __tablename__ = "seats"
    # Labels are what people see ("Floor-12"), so no two seats in one event
    # may share one. Its leading column also makes "all seats of an event" fast.
    __table_args__ = (UniqueConstraint("event_id", "label"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"))
    tier_id: Mapped[int] = mapped_column(ForeignKey("tiers.id"), index=True)
    label: Mapped[str] = mapped_column(String(120))
