# Primer 7: Relational databases (tables, keys, constraints)

**Analogy:** a database is a set of spreadsheets with a very strict
librarian. Each sheet (**table**) has fixed columns. The librarian refuses any
row that breaks a rule, however politely the app asks.

## The words

| Word | Meaning | Example here |
|---|---|---|
| Table | A named grid of data | `tiers` |
| Row | One record | the "Floor" tier of one concert |
| Column | One field, with a type | `capacity INTEGER NOT NULL` |
| Primary key | The column that uniquely identifies a row | `id` |
| Foreign key | A column that must point at an existing row elsewhere | `tiers.event_id` -> `events.id` |
| NOT NULL | The value is required | `email` |
| UNIQUE | No two rows may share this value (or combination) | `username`; `(event_id, name)` |
| CHECK | A true/false rule every row must pass | `sold >= 0 AND sold <= capacity` |
| Default | The value used when none is given | `role` defaults to `'USER'` |
| Transaction | A group of changes that all happen, or none do | the S1.1 demo rolls everything back |
| Index | A lookup structure that makes searching fast (like a book's index) | made automatically for UNIQUE |

## Why rules live in the database, not just in Python

The app checks things too, but code has bugs, and in Phase E three API
replicas plus a worker all write at once. A CHECK constraint is applied by
Postgres to **every** write, from every process, every time. That's why
section 6 calls the database the **source of truth**. Redis is fast, but if it
is ever wrong, `ck_tiers_sold_within_capacity` still refuses to oversell.

## Models: tables as Python classes (SQLAlchemy)

`app/db/models.py` describes each table as a class:

```python
class Tier(Base):
    __tablename__ = "tiers"
    capacity: Mapped[int]  # INTEGER NOT NULL
    sold: Mapped[int] = mapped_column(default=0, server_default="0")
```

`Mapped[int]` means NOT NULL, and `Mapped[str | None]` means NULL is allowed.
SQLAlchemy turns these classes into `CREATE TABLE` statements. In S1.2,
Alembic will turn them into **migrations** (versioned scripts that change the
real database step by step).

## Try it

```
uv run python -m learning.examples.s1_1.constraints_demo
```

It creates the tables in a throwaway schema, tries to break every rule, prints
which named constraint stopped each attempt, then rolls everything back.
