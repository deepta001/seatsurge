"""Tests that the table models declare the rules from CLAUDE.md section 6.

These check the SQL that would be sent to Postgres, without a database. The
rules actually firing in Postgres is shown by learning/examples/s1_1.
"""

from sqlalchemy import CheckConstraint, ColumnDefault, Table, UniqueConstraint
from sqlalchemy.dialects.postgresql.base import PGDialect
from sqlalchemy.schema import CreateTable

# Importing the models module registers its tables on Base.metadata.
from app.db import models
from app.db.base import Base

# Looked up through metadata (typed as Table) rather than Model.__table__,
# which mypy only knows as a generic "FromClause".
USERS = Base.metadata.tables["users"]
EVENTS = Base.metadata.tables["events"]
TIERS = Base.metadata.tables["tiers"]


def create_table_sql(table: Table) -> str:
    # SQLAlchemy's dialect classes ship without type hints, so mypy can't check this call.
    dialect = PGDialect()  # type: ignore[no-untyped-call]
    return str(CreateTable(table).compile(dialect=dialect))


def check_constraint_names(table: Table) -> set[str]:
    return {str(c.name) for c in table.constraints if isinstance(c, CheckConstraint)}


def test_all_tables_are_registered() -> None:
    assert set(Base.metadata.tables) == {
        "users",
        "events",
        "tiers",
        "refresh_tokens",
        "orders",
        "tickets",
        "outbox_events",
        "processed_messages",
    }


def test_user_email_and_username_are_unique() -> None:
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in USERS.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("email",) in unique_columns
    assert ("username",) in unique_columns


def test_new_users_default_to_the_user_role_in_python_and_in_the_database() -> None:
    python_default = USERS.c.role.default
    assert isinstance(python_default, ColumnDefault)
    assert python_default.arg == models.UserRole.USER
    assert "role VARCHAR(32) DEFAULT 'USER' NOT NULL" in create_table_sql(USERS)


def test_role_only_allows_user_or_admin() -> None:
    assert "CHECK (role IN ('USER', 'ADMIN'))" in create_table_sql(USERS)


def test_tier_has_the_oversell_backstop_constraints() -> None:
    assert check_constraint_names(TIERS) >= {
        "ck_tiers_capacity_positive",
        "ck_tiers_sold_within_capacity",
        "ck_tiers_price_not_negative",
        "ck_tiers_next_number_not_negative",
    }
    assert "CHECK (sold >= 0 AND sold <= capacity)" in create_table_sql(TIERS)


def test_tier_names_are_unique_within_an_event() -> None:
    assert "CONSTRAINT uq_tiers_event_id_name UNIQUE (event_id, name)" in create_table_sql(TIERS)


def test_event_seating_and_status_are_restricted_and_status_defaults_to_draft() -> None:
    sql = create_table_sql(EVENTS)
    assert "CHECK (seating IN ('GENERAL_ADMISSION', 'RESERVED'))" in sql
    assert "CHECK (status IN ('DRAFT', 'PUBLISHED', 'CANCELLED'))" in sql
    assert "status VARCHAR(32) DEFAULT 'DRAFT' NOT NULL" in sql


def test_money_is_stored_as_whole_cents() -> None:
    assert "price_cents INTEGER NOT NULL" in create_table_sql(TIERS)
