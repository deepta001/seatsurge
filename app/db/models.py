"""Table models for users, events and tiers: each class describes one Postgres table.

The constraints here are the database's own rules. They hold even if the app
code has a bug, which is what makes the database the source of truth.
"""

import enum
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserRole(enum.StrEnum):
    USER = "USER"
    ADMIN = "ADMIN"


class SeatingType(enum.StrEnum):
    GENERAL_ADMISSION = "GENERAL_ADMISSION"
    RESERVED = "RESERVED"


class EventStatus(enum.StrEnum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    CANCELLED = "CANCELLED"


def status_column_type(enum_class: type[enum.StrEnum], name: str) -> Enum:
    """Store an enum as text guarded by a CHECK constraint (e.g. role IN ('USER', 'ADMIN')).

    Postgres also has native enum types, but they're awkward to change in
    migrations. Text plus CHECK rejects bad values just as firmly.
    """
    return Enum(
        enum_class,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        validate_strings=True,
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 320 is the longest legal email address.
    email: Mapped[str] = mapped_column(String(320), unique=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    # Only ever a hash (S1.3), never the password itself.
    password_hash: Mapped[str] = mapped_column(String(255))
    # Defaults to USER in Python and in the database, so a row can't be created
    # as ADMIN by accident (CLAUDE.md section 9).
    role: Mapped[UserRole] = mapped_column(
        status_column_type(UserRole, "user_role"),
        default=UserRole.USER,
        server_default=UserRole.USER.value,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    # timezone=True stores an exact moment, so "20:00 in London" stays correct
    # whatever time zone the server or the user is in.
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    venue: Mapped[str] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(100))
    seating: Mapped[SeatingType] = mapped_column(status_column_type(SeatingType, "seating"))
    status: Mapped[EventStatus] = mapped_column(
        status_column_type(EventStatus, "event_status"),
        default=EventStatus.DRAFT,
        server_default=EventStatus.DRAFT.value,
    )
    # No ON DELETE CASCADE: deleting a user must never silently delete events.
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))


class Tier(Base):
    """One price level of an event (e.g. 'Floor'), with its capacity and sold count."""

    __tablename__ = "tiers"
    __table_args__ = (
        UniqueConstraint("event_id", "name"),
        CheckConstraint("capacity > 0", name="capacity_positive"),
        # The oversell backstop: Postgres rejects any update that would push
        # sold past capacity, even if Redis or the app got it wrong (section 6).
        CheckConstraint("sold >= 0 AND sold <= capacity", name="sold_within_capacity"),
        CheckConstraint("price_cents >= 0", name="price_not_negative"),
        CheckConstraint("next_number >= 0", name="next_number_not_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"))
    name: Mapped[str] = mapped_column(String(100))
    # Money as whole cents, never a float: 0.1 + 0.2 != 0.3 in floating point.
    price_cents: Mapped[int]
    capacity: Mapped[int]
    sold: Mapped[int] = mapped_column(default=0, server_default="0")
    # The last ticket number handed out. Numbers are never reused, even after
    # a cancellation, so this only ever goes up.
    next_number: Mapped[int] = mapped_column(default=0, server_default="0")
