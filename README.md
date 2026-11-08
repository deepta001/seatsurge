# seatsurge

A ticket booking backend that stays correct when thousands of people try to
buy the same limited seats at once.

> **Status:** early setup (step S0.4). Nothing in this README is a working
> feature yet; features are only listed here once a test demonstrates them.

## Planned architecture

```
client -> nginx -> api (x3) --Lua--> Redis (holds, counters)
                      |
                      +--txn--> Postgres (orders + outbox_events)
                                     |
                         relay (SKIP LOCKED) --XADD--> Redis Stream
                                                           |
                                         worker (consumer group, idempotent)
                                                           |
                       Postgres (tickets, tier sold counters) + pub/sub -> SSE
```

## Folder layout

| Folder | What goes in it |
|---|---|
| `app/api/` | HTTP routes, request/response schemas, error handlers |
| `app/core/` | Settings, security, logging, typed errors |
| `app/db/` | Postgres table models and sessions |
| `app/redis/` | Redis client, Lua scripts and their wrappers |
| `app/services/` | Business logic: holds, orders, events, auth |
| `app/worker/` | Background tasks: outbox relay, stream consumer, hold sweeper |
| `tests/` | `unit/`, `integration/`, `concurrency/`, `adversarial/` |
| `docs/` | Design notes, learning log, glossary |
| `learning/` | Concept primers and small runnable examples |

`migrations/`, `loadtest/`, `scripts/` and `deploy/` are added in the steps
that first need them.

## Requirements

Python 3.12, [uv](https://docs.astral.sh/uv/), Git and Docker Desktop.

```
cp .env.example .env               # then replace every CHANGE_ME
uv sync
docker compose up -d --wait        # Postgres 16 + Redis 7
uv run python -m scripts.check_connections
uv run python -m alembic upgrade head   # create or update the database tables
uv run python -m uvicorn app.main:app --reload
uv run python -m pytest -v         # run the tests
uv run python -m ruff check .      # lint
uv run python -m ruff format .     # auto-format
uv run python -m mypy              # type check
```

CI (`.github/workflows/ci.yml`) runs ruff, mypy and pytest on every push to
`main` and on every pull request.

Health checks: `GET /health/live` (is the process up?) and `GET /health/ready`
(can it reach Postgres and Redis? It returns 503 if not). Both are covered by
`tests/unit/test_health.py`.

Registration: `POST /auth/register` creates a `USER` account (never an admin)
and stores only an argon2 password hash. A duplicate email or username gets a
409. Covered by `tests/integration/test_register.py` and adversarial test 15.

Login: `POST /auth/login` returns a 15-minute HS256 JWT access token. Protected
routes (so far `GET /me`) read it from `Authorization: Bearer <token>` without
a database query. Covered by `tests/unit/test_tokens.py`,
`tests/unit/test_me.py` and `tests/integration/test_login.py`.

Refresh: login also returns a 7-day, single-use refresh token (stored only as
a SHA-256 hash). `POST /auth/refresh` swaps it for a new pair; replaying a used
one revokes that login's whole token family; `POST /auth/logout` revokes it.
Covered by `tests/integration/test_refresh.py`. Design notes are in
`docs/design.md`.

The integration and adversarial tests start a throwaway Postgres in Docker
(testcontainers), so Docker Desktop must be running for `pytest`.

Then open http://127.0.0.1:8000/docs. On Windows, use `python -m uvicorn`
rather than `uvicorn`, because Smart App Control blocks the unsigned launcher
in `.venv\Scripts`.

## Out of scope

Kafka, a front-end app, microservices, real payments and Kubernetes.
