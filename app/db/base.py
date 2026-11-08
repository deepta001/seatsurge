"""The shared base class for every table model, plus a naming rule for constraints."""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Give every index and constraint a predictable name (for example
# "ck_tiers_sold_within_capacity"). Alembic (S1.2) needs stable names to change
# or drop constraints later, and clear names make database errors readable.
NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
}


class Base(DeclarativeBase):
    """Every model inherits from this, so they all share one `metadata` (the list of tables)."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
