# seatsurge

[![CI](https://github.com/deepta001/seatsurge/actions/workflows/ci.yml/badge.svg)](https://github.com/deepta001/seatsurge/actions/workflows/ci.yml)

A ticket booking backend that stays correct when thousands of people try to
buy the same limited seats at the same instant.

Python 3.12, FastAPI, PostgreSQL 16, Redis 7 (Lua scripts, Streams,
pub/sub), SQLAlchemy 2 async, Alembic, Docker Compose with nginx in front of
three API replicas, Prometheus and Grafana, structured JSON logs.

> **Status:** complete through the hardening phase (CLAUDE.md phases 0 to E).
> The stretch goals (virtual waiting room, OpenTelemetry tracing) are not
> built. This README lists only what a test or a recorded run demonstrates.

## Results (measured; details in [`docs/benchmarks.md`](docs/benchmarks.md))

1,000 buyers compete for 100 seats at the same instant, through nginx and 3
API replicas, on one laptop (Intel Core Ultra 5 226V, 8 cores, Docker
Desktop; the load generator on the same machine). Median of 5 runs:

| | |
|---|---|
| Tickets issued / oversold | 100 / **0** in every run |
| ... with the worker SIGKILLed, or Redis FLUSHALLed, mid-sale | 100 / **0**, Postgres and Redis consistent afterwards |
| Failed requests | 0 |
| Postgres and Redis agree afterwards | yes, every run (`scripts/verify_consistency.py`) |
| Hold latency, client side, p50 / p95 / p99 | 2.2 s / 2.9 s / 3.0 s |
| Throughput during the burst | ~356 requests/s (all 1,100 requests in ~3.1 s) |

The latency is queueing, not work: Redis runs each atomic script in ~52 us,
but each replica is one Python process at 100% of a core during the burst,
and the laptop as a whole is at 85 to 92% CPU. These are correctness results
under load, not capacity figures.

## How it works

```
client -> nginx -> api (x3) --Lua--> Redis (holds, counters, idempotency, rate limits)
                      |
                      +--one txn--> Postgres (orders + outbox_events)
                                          |
                          relay (FOR UPDATE SKIP LOCKED) --XADD--> Redis Stream
                                                                       |
                                              worker (consumer group, idempotent)
                                                                       |
                      Postgres (tickets, tier counters) + pub/sub -> SSE live updates
```

1. **Hold.** `POST /events/{id}/holds` runs one Lua script in Redis that
   checks and takes seats atomically (all or nothing, also for chosen
   seats), records a hold that expires in 5 minutes, and enforces a
   per-user cap. A missing counter is rebuilt from Postgres under a lock,
   never read as zero.
2. **Confirm.** `POST /holds/{id}/confirm` takes only the hold id: seats,
   quantity and price come from the server. One Postgres transaction writes
   a PENDING order and an outbox row. Answer: 202.
3. **Relay.** A worker task moves committed outbox rows to a Redis Stream,
   each row in its own try/except, with backoff and a DEAD state.
4. **Issue.** The worker reads the stream as a consumer group, handles each
   message once (`processed_messages` in the same transaction), issues
   numbered tickets with a conditional `UPDATE tiers ... WHERE sold + q <=
   capacity`, and acks only after the commit. Failures retry with backoff,
   then go to a dead-letter stream and give the seats back.
5. **Expire, cancel, recover.** A sweeper returns abandoned holds' seats;
   cancellation goes through the outbox too; an admin reconcile rebuilds
   Redis from Postgres after a Redis loss.
6. **Watch.** `GET /events/{id}/stream` (Server-Sent Events) shows live
   availability, at most 5 updates a second per event, on any replica.

### Why it can't oversell

- **The fast gate is atomic:** every inventory change is one Lua script, so
  "check, then take" can't interleave between requests.
- **The database is the backstop:** `sold <= capacity` is a CHECK, issuing is
  a conditional UPDATE, and a seat can have only one live ticket (partial
  unique index). Even with Redis wrong or wiped, Postgres refuses to oversell;
  `invariant_violations_total` counts any time it had to.
- **Nothing is lost between the two:** the outbox makes "order written" and
  "order will be processed" one commit; the stream is at-least-once and every
  consumer is idempotent.

Each decision, the alternative and the trade-off are in
[`docs/design.md`](docs/design.md); each failure and the test that covers it
in [`docs/failure-modes.md`](docs/failure-modes.md).

## What's built (and what proves it)

| Area | What it does | Proven by |
|---|---|---|
| Accounts | Self-registration is always `USER` (admins only from a CLI); argon2 hashes; 15-min JWT access tokens; rotating single-use refresh tokens with reuse detection; auth on requests reads only the token | adversarial test 15, `tests/integration/test_refresh.py`, `tests/unit/test_me.py` |
| Events | Admin CRUD with tiers (general admission or reserved seats); one-way DRAFT -> PUBLISHED -> CANCELLED; public listing with search, city filter and paging; seat map | `tests/integration/test_events_admin.py`, `test_events_public.py`, `test_seat_map.py` |
| Never oversell | 500 concurrent HTTP buyers on 50 seats, 1-4 seats each, never exceed 50; fails if the Lua script is swapped for naive check-then-take | test 1 (`tests/concurrency/`) |
| Holds | Atomic Lua reserve (tier or specific seats, all or nothing); 5-min TTL; per-user cap; missing counter rebuilt, never zero; idempotent release; sweeper | tests 5, 6, 12, `test_seat_holds.py` |
| Confirm | Takes only a hold id; forged or foreign holds get nothing; client-sent seats/quantities ignored; order + outbox row in one transaction; per-user purchase cap | tests 2, 3, `test_confirm_api.py` |
| Pipeline | Outbox relay with SKIP LOCKED, backoff, DEAD state; consumer group; idempotent handling; retries, dead letters, seats released for failed orders | tests 7, 8, 9, 10, 16 |
| Backstops | Conditional UPDATE and unique indexes refuse an oversell or a double-sold seat even with Redis wiped | tests 4, 4b |
| Recovery | Redis flushed mid-sale: no oversell, consumer group recreated, reconcile re-queues lost orders | test 11, chaos runs |
| Cancel | Through the outbox; seats back once; ticket numbers never reused | test 13 |
| Protection | Sliding-window rate limits (holds per user; logins per email and per IP), 429 + Retry-After; CORS allowlist; no default secrets; errors never leak internals; non-root containers; real client IP behind nginx | test 14, `test_security_hardening.py`, `test_deploy_config.py`, [`docs/security-checklist.md`](docs/security-checklist.md) |
| Live updates | SSE per event via Redis pub/sub; coalesced fresh snapshots; one subscription per process; no DB connection held by a stream | `tests/integration/test_live_updates.py` |
| Operations | 3 replicas behind nginx; Prometheus metrics and a provisioned Grafana dashboard; JSON logs with a correlation id carried from nginx through the outbox to the worker | `test_metrics.py`, `test_correlation.py` |
| Load and chaos | Locust load test, `verify_consistency.py`, chaos runner (kill worker, flush Redis, two workers), benchmark runner | `loadtest/`, `tests/integration/test_verify_consistency.py` |

**Tests:** 350 (75 unit, 196 integration, 7 concurrency, 72 adversarial),
against real Postgres 16 and Redis 7 started by testcontainers. A guard fails
any test that raises `invariant_violations_total` unless it trips a backstop
on purpose. CI runs ruff, mypy, all tests, every migration on an empty
database (and back down), `alembic check`, the image build, `nginx -t` and a
Makefile dry run.

## Run it

Needs Python 3.12, [uv](https://docs.astral.sh/uv/), Git and Docker Desktop.

```
cp .env.example .env          # then replace every CHANGE_ME with a long random value
uv sync
make up                       # or: docker compose up -d --build --wait
docker compose exec api python -m scripts.seed_admin --email you@example.com --username you
```

- API (nginx, 3 replicas): http://127.0.0.1:8080 (docs at `/docs` outside production)
- Prometheus: http://127.0.0.1:9090
- Grafana: http://127.0.0.1:3000 (user `admin`, password `GRAFANA_ADMIN_PASSWORD`)

Develop against just the databases:

```
docker compose up -d --wait postgres redis
uv run python -m alembic upgrade head
uv run python -m uvicorn app.main:app --reload       # http://127.0.0.1:8000
uv run python -m app.worker.main                     # in a second terminal
```

Tests and checks (Docker must be running):

```
make test                     # or: uv run python -m pytest
make lint                     # ruff, ruff format --check, mypy
```

The headline test, the consistency check, chaos and benchmarks (stack up):

```
make load                     # 1,000 buyers on 100 seats, then verify_consistency
make verify                   # exit 1 on any Postgres/Redis mismatch
make load-clean               # delete exactly what the last load run created
uv run --group load python -m loadtest.chaos kill-worker    # or flush-redis, two-workers
uv run --group load python -m loadtest.benchmark --runs 5
```

On Windows without `make`, run the command listed under each target in the
`Makefile`, and run tools as `python -m <tool>` (Smart App Control can block
the `.exe` launchers in `.venv\Scripts`).

## Repository layout

| Folder | What's in it |
|---|---|
| `app/api/` | Routes, request/response models, dependencies, error handlers, middleware (metrics, correlation id, body limit) |
| `app/core/` | Settings, security, tokens, typed errors, metrics, logging, correlation id |
| `app/db/` | Table models and sessions |
| `app/redis/` | Client, key schema, `lua/*.lua` and their typed wrappers, rehydrate, rate limiter |
| `app/services/` | Business logic: holds, orders, tickets, cancellations, reconcile, events, auth, mock payments |
| `app/worker/` | Relay, consumer, retries, dead letters, sweeper, live publisher, backlog gauges |
| `migrations/` | Alembic migrations |
| `tests/` | `unit/`, `integration/`, `concurrency/`, `adversarial/` (tests 2 to 16) |
| `loadtest/` | Locust file, prepare/cleanup, chaos runner, benchmark runner |
| `scripts/` | `seed_admin.py`, `verify_consistency.py`, `check_connections.py` |
| `deploy/` | nginx, Prometheus and Grafana configuration |
| `docs/` | Design, failure modes, benchmarks, security checklist, interview notes, glossary, learning log |
| `learning/` | Concept primers and runnable demos (including "break it on purpose" ones) |

## Known limitations

- **One machine's numbers.** The benchmarks ran the load generator on the
  same laptop as the system, which was CPU-saturated; they show correctness
  under a burst, not capacity.
- **CPU per replica.** Each replica is a single Python process; under the
  burst that core is the bottleneck. More processes help server-side time
  (measured), but weren't adopted.
- **No high availability.** One Postgres and one Redis, no replicas or
  failover. Losing Redis is survivable (tested); losing Postgres stops sales.
- **Reconcile is manual.** After a Redis loss, counters rebuild themselves,
  but re-sending lost order messages needs an admin to call reconcile.
- **Hold idempotency lives in Redis.** After a Redis flush, a retried hold
  request with the same key can create a second hold (still within the
  per-user cap). Orders have a database-level idempotency constraint.
- **Access tokens can't be revoked early** (up to 15 minutes, the
  stateless-auth trade-off). Old refresh-token rows aren't cleaned up.
- **Admin gaps:** admins can't list draft events; tiers can't be edited
  after creation; name search scans the table (no search index).
- **Payments are a mock.** No real provider; and when a paid order later
  fails in the worker (and its seats are released), nothing refunds the
  payment, because the mock lives in the API process.

## Out of scope

Kafka, a front-end app, microservices, real payments and Kubernetes
(CLAUDE.md section 2).

## Documentation

- [`docs/design.md`](docs/design.md): every decision, the alternative, and why
- [`docs/failure-modes.md`](docs/failure-modes.md): failure, what breaks, how it's prevented, the test
- [`docs/benchmarks.md`](docs/benchmarks.md): measured results and where the time goes
- [`docs/security-checklist.md`](docs/security-checklist.md): the security requirements, item by item
- [`docs/interview-notes.md`](docs/interview-notes.md): likely interview questions with honest answers
- [`docs/glossary.md`](docs/glossary.md) and [`docs/learning-log.md`](docs/learning-log.md)
