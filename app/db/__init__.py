"""PostgreSQL access: table models and database sessions. Postgres is the source of truth.

Importing this package registers every table on Base.metadata, so Alembic and
the tests always see the complete schema.
"""

from app.db import models, order_models, outbox_models, seat_models  # noqa: F401
