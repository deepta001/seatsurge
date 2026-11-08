# Primer 8: Alembic migrations

**Analogy:** migrations are a building's renovation log. You never knock the
building down to add a room. Each entry says "add this, here", in order, and
can be reversed. Any copy of the building (your laptop, CI, a server) can be
brought to the same state by replaying the log.

## Why not just "create the tables at startup"?

`Base.metadata.create_all()` only creates **missing** tables. It can't add a
column to a table that already holds data, rename something, or undo a
change. Real databases are full of data you can't throw away, so CLAUDE.md
section 6 says: Alembic only, and never auto-create the schema at startup.

## The pieces

| Piece | What it is |
|---|---|
| `alembic.ini` | Settings: where migrations live and how files are named. No database password; `env.py` reads it from `.env`. |
| `migrations/env.py` | The script Alembic runs: connects to Postgres and knows our models. |
| `migrations/versions/*.py` | One file per change, each with an `upgrade()` and a `downgrade()`. |
| `alembic_version` table | One row in the database saying which revision it's on. |
| Revision id | A random id such as `19624396e697`; each file names the one before it (`down_revision`), forming a chain. |

## The everyday commands

```
uv run python -m alembic revision --autogenerate -m "add x"   # write a migration from model changes
uv run python -m alembic upgrade head      # apply everything not yet applied
uv run python -m alembic downgrade -1      # undo the latest one
uv run python -m alembic current           # which revision is the DB on?
uv run python -m alembic check             # do the models and migrations match?
uv run python -m alembic upgrade head --sql   # print the SQL without running it
```

## Autogenerate is a draft, not gospel

`--autogenerate` compares the models with the real database and writes its
best guess. **Always read the file before applying it.** It can't detect
renames (it sees "drop column + add column", which loses data), and it ignores
some changes. A human reviews every migration.

## The CI safety net

CI applies all migrations to an empty Postgres, runs `alembic check` (which
fails if a model changed without a migration), then downgrades and upgrades
again to prove the undo path works.
