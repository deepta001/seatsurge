"""add outbox correlation_id

S8.2b: the id of the request that wrote each outbox row. Nullable, so it is
a metadata-only change in Postgres (no table rewrite) and old rows stay valid.

Revision ID: 1723e7a90bef
Revises: 52815b367d20
Create Date: 2026-11-09 20:05:21.365946
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1723e7a90bef"
down_revision: str | Sequence[str] | None = "52815b367d20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("outbox_events", sa.Column("correlation_id", sa.String(length=64), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("outbox_events", "correlation_id")
