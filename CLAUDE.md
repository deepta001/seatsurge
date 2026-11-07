# AGENTS.md: High-Concurrency Ticket Booking Backend (Python)

Project name: `<PROJECT_NAME>` (the owner picks it; do not call it Eventix).

You are helping a **complete beginner** build a portfolio-grade backend. The
student knows only basic Python (variables, functions, loops, lists/dicts,
simple classes). Assume NO prior knowledge of web frameworks, databases,
async code, Docker, Redis, testing tools or distributed systems.

Two goals, equally important:

1. Build the project correctly.
2. Make sure the student **genuinely understands** every part of it, well
   enough to explain it in an interview without notes.

If those ever conflict, **understanding wins over speed.** Prefer simple,
correct, well-tested designs over many tools, and explain non-trivial choices
in plain English.

---

## 0. How we work together (READ THIS FIRST)

### 0.1 Work in small phases, never all at once

- The project is split into **phases -> milestones -> steps** (section 13).
- Work on ONE step at a time. Never build several milestones in one go, never
  generate the whole codebase up front, and never do silent big refactors.
- A step adds a small amount of code (aim for roughly 150 new lines or fewer)
  and at most one or two new concepts.
- Do not start the next step until the student has confirmed they understand
  the current one (0.3).

### 0.2 The loop for EVERY step

1. **Preview** (before coding): in plain English, say what we are about to
   build, why it is needed, which new concepts it uses, and what the student
   will see when it works. If a concept is new, give a short primer first (0.5).
2. **Build**: write the code for just this step, in small pieces, following
   the beginner-friendly code rules (0.6). Tell the student which commands to
   run themselves; in early phases let the student type or run things.
3. **Run it**: run the code or tests and show the real output. If something
   fails, explain the error calmly and fix it (this teaches debugging).
4. **Teach** (mandatory, see 0.4): walk through every new module/file, what is
   in it, and why it is designed that way.
5. **Check understanding** (0.3): ask questions and give a small exercise.
6. **Record**: add an entry to `docs/learning-log.md` and any new terms to
   `docs/glossary.md`.
7. **Wait** for the student's go-ahead before starting the next step.

### 0.3 The understanding gate (no skipping)

After teaching a step, check that the student really understood it:

- Ask 3 to 5 questions in ONE message and then wait. Do not answer your own
  questions in the same message. Mix these kinds:
  - **Explain it in your own words** (required): "In your own words, what does
    this module do and why do we need it?"
  - **What if...?** "What would happen if two requests arrived at the same
    moment here?"
  - **Predict**: "If we change this number to 3, what will the test print?"
  - **Your turn** (small hands-on task): change a value, add a field, write a
    tiny test, or fix a planted bug. Review what the student did.
- "Yes, I get it" is NOT an answer. Require a real answer to the explain
  question and at least one prediction or "what if" question.
- If an answer is wrong or unsure: do not scold. Re-explain with a different
  analogy or a smaller demo, then ask a fresh question. Never move on with
  unresolved confusion.
- If the student is still stuck after two tries, simplify (smaller example,
  draw a diagram), mark the topic as "revisit" under **Shaky topics** in
  `docs/learning-log.md`, and bring it back in the phase review.

### 0.4 The teaching walkthrough (after a step works)

For EACH new module or file, cover:

1. **Purpose**: one sentence, "This file is responsible for ...".
2. **Where it fits**: how it connects to the other modules (a small ASCII or
   Mermaid diagram).
3. **Contents tour**: every class, function and important variable. What goes
   in, what comes out. Read the important code top to bottom in plain English
   and explain tricky lines one by one.
4. **Why it works this way**: the problem it solves, the simpler alternative
   and why that is not enough, the trade-offs, and what would break if this
   part were removed or changed.
5. **See it live**: run a tiny demo, print intermediate values, or trigger a
   failure on purpose.
6. **Real-world link**: connect it to how real ticketing sites behave, and say
   where an interviewer is likely to ask about it.

Teaching style: plain English first, jargon second. Define every technical
term the first time it appears and add it to `docs/glossary.md`. Use analogies
(e.g. "a hold is a seat with a 'reserved for 5 minutes' sticker"). Keep
explanations in short, organised chunks, not one wall of text.

**"Break it on purpose" demos** (required, because seeing a bug teaches more
than being told about it):

- Naive check-then-decrement overselling vs the Lua script (S2.1 / S2.9).
- Booking without the database unique constraint vs with it (S4.5).
- Processing the same stream message twice without idempotency (S4.4).
- Killing the relay between commit and publish (S4.7).
- Flushing Redis mid-sale and watching reconcile repair it (S5.2).

### 0.5 Concept primers (`learning/` folder)

Introduce each concept at the step where it is first needed, not all up front.
Each primer is `learning/NN-topic.md`: at most about one page, one analogy,
and a tiny runnable example in `learning/examples/`. Topics, in rough order:

1. Type hints, modules and imports, virtual environments
2. HTTP, REST, JSON and status codes
3. async/await and the event loop (why web servers use it)
4. FastAPI routes, dependencies and pydantic models
5. Settings and environment variables
6. Docker and Docker Compose
7. Relational databases: tables, keys, constraints, transactions, indexes
8. SQLAlchemy and Alembic migrations
9. Password hashing and JWT
10. Redis data types and TTLs
11. Race conditions and atomicity
12. Lua scripts inside Redis
13. Idempotency
14. The outbox pattern
15. Redis Streams and consumer groups
16. pytest, fixtures and testcontainers
17. Load testing, percentiles and metrics

### 0.6 Beginner-friendly code rules (the tech stack does not change)

- Plain, readable code: descriptive names, small functions, early returns.
  Avoid clever one-liners, metaprogramming, deep inheritance, and abstractions
  that are not needed yet. If there is a simple way and a clever way, choose
  the simple way.
- Comment the WHY (not the what) on non-obvious lines. Every module starts
  with a docstring of 1 to 3 sentences explaining its purpose; the teaching
  walkthrough should mirror it.
- Type hints everywhere (explained in primer 1).
- Roughly one new idea per file; keep files short (aim for under 200 lines).
- Every module gets at least one test, and the student is shown how to run it.
- Always give the exact commands to run and explain what the output means.

### 0.7 Adding or changing a feature later

1. Say first: what will change, which files, why, and what could go wrong.
   Wait for the student's OK for anything beyond a tiny change.
2. Make the smallest change that works; show the diff and explain each changed
   part; run the tests, including the relevant adversarial tests.
3. Explain how it interacts with existing modules (what else could it affect?).
4. Run the understanding gate (0.3) for the new feature, exactly like a new
   step.
5. Update tests, README claims, `docs/design.md`, `docs/failure-modes.md`
   (if relevant), `docs/learning-log.md` and `docs/glossary.md`.
6. If the change makes an earlier explanation outdated, tell the student what
   is different now and why.

### 0.8 Phase reviews

At the end of every phase:

1. Demo the working system.
2. Draw a recap diagram of the system so far.
3. Run an 8 to 10 question review quiz that includes the **Shaky topics**.
4. **Teach it back**: ask the student to explain the phase's request flow in
   their own words and give feedback.
5. Update README and `docs/design.md`.
6. Suggest resume-ready wording ONLY for things that exist and are tested.
   No unmeasured numbers.

### 0.9 Student controls and tone

The student can say at any time: "slower" (smaller steps, more analogies),
"explain again", "quiz me", "show me the code path for X", "skip the quiz"
(once; note it in the log) or "pause". Always honour these.

- At the start of each phase, ask how confident the student feels (1 to 5) and
  adjust the pace.
- Be friendly and patient, celebrate small wins, never be condescending.
- If you make a mistake, say so plainly and fix it.
- At the very start, ask which operating system the student uses (Windows,
  macOS, Linux) and give OS-specific install steps for Python 3.12, Git, `uv`
  and Docker Desktop.

### 0.10 Resuming a session

Work will span many sessions. At the start of every session: re-read this file
and `docs/learning-log.md`, say where we stopped, list any Shaky topics, ask the
student two quick recall questions about the last step, and only then continue.

---

## 1. Goal and success criteria

Build a ticket booking backend that stays **correct** when thousands of users
compete for limited seats ("thundering herd").

Headline acceptance test (must pass and be reproducible with one command):

> 1,000 concurrent simulated users compete for 100 seats, through a load
> balancer, against **3 API replicas**. Result: exactly 100 tickets issued,
> 0 oversold, DB and Redis agree after the queue drains, and the same result
> holds when the worker is killed mid-run and when Redis is flushed mid-run.

Priority order: correctness > clarity > observability > speed.
Only report performance numbers that were actually measured.

## 2. Stack (fixed; ask before adding anything)

- Python 3.12, `uv` for dependencies, `ruff` + `mypy` (strict on `app/services`)
- FastAPI (async), pydantic v2, pydantic-settings
- PostgreSQL 16, SQLAlchemy 2.0 (async, asyncpg), Alembic migrations
- Redis 7 (`redis.asyncio`): Lua scripts, Streams, pub/sub
- PyJWT, argon2-cffi (or bcrypt) for passwords
- pytest, pytest-asyncio, testcontainers-python, Locust
- prometheus-client, structlog (JSON logs)
- Docker Compose; nginx only as a round-robin load balancer
- GitHub Actions CI

NOT in scope: Kafka, Angular/React SPA, microservices, real payments,
Kubernetes. One codebase, two process types: `api` and `worker`.

## 3. Architecture in one paragraph

Redis is the **fast gate** (atomic inventory + expiring holds). PostgreSQL is
the **source of truth** and has constraints that make overselling impossible
even if Redis is wrong. A client first creates a **hold** (time-limited
reservation), then **confirms** it. Confirm writes an order and an outbox row in
one DB transaction. A relay moves outbox rows to a Redis Stream; a worker
consumes the stream idempotently, issues tickets, and publishes live updates.

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

Processes: `api` (uvicorn, scaled to 3) and `worker` (one container running
three asyncio tasks: outbox relay, stream consumer, hold sweeper).

## 4. Core rules (the design invariants)

1. **Never trust the client for what it owns.** Confirm takes only a `hold_id`.
   Seat ids, quantities and prices come from the server-side hold, never the
   request body. A forged or foreign hold id must fail.
2. **Every hold expires.** General-admission and per-seat holds alike have a TTL
   (default 5 min). Abandoned holds always return inventory.
3. **Inventory changes are atomic.** One Lua script updates everything for a
   reservation, all-or-nothing, including multi-seat requests. Never do
   DECR-then-undo from application code.
4. **A missing Redis key is never "zero".** Missing counter = not initialised =
   run a locked (single-flight) rehydrate from the DB, then retry.
5. **The database enforces the truth.** Unique constraints and conditional
   updates are the backstop (section 6). Redis mistakes must not become
   double sales.
6. **Redis changes that depend on a DB commit happen after the commit**, via the
   outbox/worker. Never mutate Redis inventory in a request handler before the
   DB transaction commits (cancellations, refunds, etc.).
7. **No hot rows.** No per-order `UPDATE` on a shared "available seats" column,
   and no ORM `@Version` on rows every order touches.
8. **At-least-once delivery + idempotent consumers.** Duplicates must be
   harmless.
9. **Failures are typed.** Use exception classes (`PermanentError`,
   `TransientError`, domain errors), never string matching on messages.
10. **Never leak internals.** Client errors never include raw exception text.

## 5. Redis design

Key schema (use hash tags like `{event_id}` if clustering is ever added):

| Key | Type | Purpose |
|---|---|---|
| `inv:{event}:{tier}:avail` | string int | live available count for a tier |
| `hold:{hold_id}` | hash | user, event, tier/seat ids, qty, status, expires_at |
| `holds:expiry` | zset | score = expires_at ms, member = hold_id |
| `uhold:{event}:{user}` | string int | tickets currently held by a user (cap) |
| `seat:{event}:{seat_id}` | string | holds a reserved seat (value = hold_id) |
| `sold:{event}` | set | seat ids already sold (reserved seating) |
| `idem:{user}:{key}` | string | stored response for an Idempotency-Key (24h) |
| `stream:orders`, `stream:orders:dead` | stream | order fulfilment and dead letters |
| `chan:event:{event}` | pub/sub | live availability updates |

Hold status machine: `HELD -> CONFIRMING -> CONSUMED`, or `HELD -> RELEASED`
or `EXPIRED`.

Required Lua scripts (implement, unit test each in isolation):

- `reserve_tier.lua` (general admission). Sketch:
  ```lua
  -- KEYS: 1=avail 2=hold 3=holds:expiry 4=uhold
  -- ARGV: 1=qty 2=hold_id 3=user 4=expires_at_ms 5=user_cap 6=ttl_s 7=tier
  local qty = tonumber(ARGV[1])
  local avail = tonumber(redis.call('GET', KEYS[1]) or '')
  if avail == nil then return -2 end            -- NOT_INITIALISED: rehydrate
  local held = tonumber(redis.call('GET', KEYS[4]) or '0')
  if held + qty > tonumber(ARGV[5]) then return -3 end  -- user cap
  if avail < qty then return -1 end                      -- sold out
  redis.call('DECRBY', KEYS[1], qty)
  redis.call('INCRBY', KEYS[4], qty)
  redis.call('HSET', KEYS[2], 'user', ARGV[3], 'tier', ARGV[7], 'qty', qty,
             'status', 'HELD', 'expires_at', ARGV[4])
  redis.call('EXPIRE', KEYS[2], tonumber(ARGV[6]) + 900)
  redis.call('ZADD', KEYS[3], ARGV[4], ARGV[2])
  return 1
  ```
- `reserve_seats.lua` (reserved seating): for every requested seat check
  `seat:{event}:{id}` does not exist and the seat is not in `sold:{event}`;
  only if ALL are free, `SET` every seat key to the hold id. All or nothing.
- `consume_hold.lua`: verify the hold exists, belongs to the caller, is `HELD`,
  and is not expired; set `CONFIRMING`. Returns the hold data (server-side
  truth for qty/seats).
- `release_hold.lua`: return inventory for a hold exactly once (idempotent;
  check status), delete seat keys, adjust `uhold`, remove from `holds:expiry`.
- `rate_limit.lua`: sliding window or token bucket.

Rehydrate (also exposed as an admin reconcile endpoint and run on cache miss,
single-flight via a Redis lock):

```
avail = capacity - sold(DB) - quantity held by active holds
        - quantity of PENDING orders not yet fulfilled
```

Pending orders must be counted, otherwise a rehydrate during a sale oversells.

## 6. Database design

Use enums for status fields (no free strings for event type). Money as integer
cents. Alembic only: never auto-create the schema at startup.

- `users(id, email UNIQUE, username UNIQUE, password_hash, role, created_at)`
- `events(id, name, description, starts_at, venue, city, seating
  ['GENERAL_ADMISSION','RESERVED'], status, created_by)`
- `tiers(id, event_id FK, name, price_cents, capacity CHECK>0,
  sold int CHECK(sold>=0 AND sold<=capacity), next_number int)`
  `UNIQUE(event_id, name)`
- `seats(id, event_id, tier_id, label)` `UNIQUE(event_id, label)`
  (pre-created for reserved seating)
- `orders(id uuid, user_id, event_id, hold_id UNIQUE, idempotency_key,
  status ['PENDING','CONFIRMED','FAILED','CANCELLED'], total_cents,
  created_at)` `UNIQUE(user_id, idempotency_key)`
- `tickets(id, order_id, event_id, tier_id, seat_id NULL, ticket_number,
  status ['ISSUED','CANCELLED'])`
  - partial unique `(event_id, seat_id) WHERE status='ISSUED'`
  - partial unique `(tier_id, ticket_number) WHERE status='ISSUED'`
  - index `(user via order)`, `(event_id, status)`
- `outbox_events(id bigserial, type, aggregate_id, payload jsonb,
  status ['PENDING','PUBLISHED','DEAD'], attempts, last_error,
  next_retry_at, created_at, published_at)`
  partial index on `(next_retry_at) WHERE status='PENDING'`
- `processed_messages(message_id PRIMARY KEY, processed_at)`

DB backstop for general admission (single atomic statement, no read-modify-write,
no ORM version column):

```sql
UPDATE tiers
   SET sold = sold + :q, next_number = next_number + :q
 WHERE id = :tier AND sold + :q <= capacity
RETURNING next_number;   -- 0 rows updated => invariant violation
```

Ticket numbers are `next_number - q + 1 .. next_number`. Cancelling decrements
`sold` only (numbers are never reused).

For reserved seating, issuing a ticket for a seat that already has an `ISSUED`
ticket violates the partial unique index.

If a backstop ever fires, treat as `PermanentError`: refund the hold, mark the
order FAILED, and increment `invariant_violations_total`. In every test and in
the load test this metric must be **0**.

## 7. Request flow

1. `POST /events/{id}/holds`: requires `Idempotency-Key` (client-generated).
   Rate limited. Runs the reserve script. Returns `201 {hold_id, expires_at}`,
   `409 sold_out`, `429 rate_limited`, or `422` for a bad request. Same key +
   same body returns the stored response; same key + different body returns 422.
2. `POST /holds/{id}/confirm`: requires `Idempotency-Key` and a `payment_token`
   from the mock payment step (configurable failure rate for tests).
   - Run `consume_hold` (HELD -> CONFIRMING).
   - One DB transaction: insert `orders(PENDING)` and an `outbox_events` row.
   - On DB failure: revert the hold to `HELD` if not expired.
   - Respond `202 {order_id, status: PENDING}`.
   - Enforce a per-user purchase cap per event in the DB (default 10 tickets).
3. **Relay task**: `SELECT ... WHERE status='PENDING' AND next_retry_at<=now()
   ORDER BY id LIMIT 50 FOR UPDATE SKIP LOCKED`. Process **each row in its own
   try/except** so one bad row never blocks others. `XADD` to `stream:orders`,
   then mark PUBLISHED. On failure: increment `attempts`, set `last_error`,
   exponential backoff via `next_retry_at`; move to `DEAD` after N attempts and
   alert. Periodically delete old PUBLISHED rows.
4. **Worker task** (consumer group, `XREADGROUP`, `XACK` only after the DB commit):
   - Insert into `processed_messages` first; a duplicate means skip and ack.
   - Issue tickets (section 6 backstop), set order `CONFIRMED`, mark hold
     `CONSUMED`, decrement `uhold`.
   - `TransientError`: do not ack; retry with backoff (use `XAUTOCLAIM` for
     stuck messages).
   - `PermanentError` or delivery count > N: move to `stream:orders:dead`,
     mark the order `FAILED`, **release inventory** via `release_hold`, and
     increment a metric. A dead-lettered order must never leak inventory.
5. **Hold sweeper task**: pops expired holds from `holds:expiry` and releases
   them. For `CONFIRMING` holds past expiry plus a grace period, check the DB:
   if an order exists for the hold, leave it; otherwise release.
6. **Cancellation**: `POST /orders/{id}/cancel` changes DB state in a
   transaction and writes an outbox event; the worker releases Redis
   inventory after the commit.
7. **Live updates**: after each state change, publish one compact message to
   `chan:event:{id}`. Never publish intermediate or negative values. Coalesce
   to at most 5 messages/sec/event. `GET /events/{id}/stream` is an SSE
   endpoint subscribing per event, so it works across all replicas.

## 8. API surface

- Auth: `POST /auth/register`, `/auth/login`, `/auth/refresh`
- Events: `GET /events` (paginated, `query`, `city`), `GET /events/{id}`,
  `GET /events/{id}/seats` (reserved seating: compact `{seat_id, state}` list
  only), `GET /events/{id}/stream` (SSE), admin: `POST/PATCH/DELETE /events`
- Holds and orders: `POST /events/{id}/holds`, `DELETE /holds/{id}`,
  `POST /holds/{id}/confirm`, `GET /orders/{id}`, `GET /me/orders`,
  `POST /orders/{id}/cancel`
- Ops: `GET /health/live`, `/health/ready`, `/metrics` (internal network
  only), admin `POST /admin/events/{id}/reconcile`

Error mapping: SoldOut 409, HoldExpired 410, NotFound 404, Forbidden 403,
Validation 422, RateLimited 429 (with `Retry-After`), Unexpected 500 (generic
message + correlation id; details only in logs).

Responses never serialize whole ORM objects. Use explicit pydantic response
models (no nested full event inside every ticket).

## 9. Security

- Self-registration is **always** the `USER` role. Admin accounts are created
  only by a CLI command or env-seeded value. No default credentials anywhere.
- JWT access token (15 min) carrying user id and role, plus a refresh token.
  The auth dependency must NOT hit the DB on every request.
- Passwords: min length, argon2/bcrypt. Login endpoint rate limited.
- CORS: origin allowlist from env. No wildcard with credentials.
- No test or simulation endpoints inside the application. Load generation
  lives in `loadtest/` and runs from outside.
- Secrets only from `.env` (provide `.env.example`); Redis requires a password;
  `/metrics` is not publicly routed; containers run as non-root.
- Cap request sizes, e.g. at most 10 seats/tickets per hold and a per-user
  hold cap (repeated hold calls must not bypass it).

## 10. Observability

Prometheus metrics: request latency histogram (by route), holds created /
rejected (by reason), orders confirmed / failed, outbox pending count and
oldest-pending age, stream pending count, dead-letter count, hold expiries,
`invariant_violations_total`, Redis script latency. One Grafana dashboard
provisioned from JSON in the repo. Structured JSON logs with a correlation id
carried API -> outbox row -> worker. OpenTelemetry tracing is an optional
stretch goal.

## 11. Testing standards

Unit tests per module; integration tests with testcontainers (real Postgres and
Redis). Record nothing against external services.

Concurrency tests must: use a start barrier (`asyncio.Event` / latch) so all
tasks begin together; assert the **specific** error type (SoldOut), not "any
exception"; verify DB **and** Redis state afterwards; use more requesters than
seats (e.g. 500 on 50) including multi-seat requests.

Adversarial tests (each one is a named test and a row in
`docs/failure-modes.md`):

1. N concurrent holds on C seats give exactly C successes (HTTP, 3 replicas).
2. Forged or foreign `hold_id` at confirm time gets no tickets.
3. Client-supplied seat ids/quantity at confirm time are ignored.
4. Seat sold -> lock TTL passes -> second purchase is rejected (DB unique
   constraint is the last line of defence; test it directly with Redis wiped).
5. Hold created then abandoned: inventory returns after TTL.
6. Same `Idempotency-Key` retried creates exactly one hold / one order.
7. Worker processes the same stream message twice: no double tickets.
8. Poison outbox row does not block later rows; ends in DEAD with `last_error`.
9. Worker fails N times: order FAILED, message dead-lettered, **inventory
   released** (no leak).
10. Relay crashes after DB commit, before publish: event delivered eventually.
11. Redis flushed mid-sale: no oversell; reconcile restores correct counts
    (including pending orders and active holds).
12. Missing Redis counter is rehydrated, never treated as zero.
13. Cancel then re-buy works; ticket numbers are never reused.
14. Rate limiting returns 429 and recovers after the window.
15. Self-registration cannot create an admin.
16. Two workers for the same event do not conflict (no hot-row retries).

Load test (`loadtest/locustfile.py`): 1,000 users, 100 seats, 3 replicas.
Then run `scripts/verify_consistency.py` (compares DB tickets, tier counters,
Redis counters; non-zero exit on any mismatch). Save measured results to
`docs/benchmarks.md` with machine specs, p50/p95/p99 latency, throughput,
sold, oversold (must be 0).

## 12. Repository layout

```
app/
  api/            routers, dependencies, error handlers, response schemas
  core/           settings, security, logging, errors (typed exceptions)
  db/             models, session, migrations helpers
  redis/          client, lua/*.lua, script wrappers, rehydrate
  services/       holds, orders, events, auth, payments(mock), rate_limit
  worker/         relay.py, consumer.py, sweeper.py, main.py
migrations/       Alembic
tests/            unit/, integration/, concurrency/, adversarial/
loadtest/         locustfile.py
scripts/          verify_consistency.py, seed_admin.py
deploy/           nginx.conf, prometheus.yml, grafana dashboard JSON
docs/             design.md, failure-modes.md, benchmarks.md, interview-notes.md,
                  learning-log.md, glossary.md
learning/         concept primers (NN-topic.md) and examples/ (runnable demos)
docker-compose.yml  Dockerfile  Makefile  .env.example  README.md  AGENTS.md
```

`docker-compose.yml`: `postgres`, `redis`, `api` (replicas: 3), `worker`,
`nginx`, `prometheus`, `grafana`. Healthchecks, DB pool sized so
`pool_size * api_replicas + worker < max_connections`; document the
calculation in `docs/design.md`. `make up`, `make test`, `make load`,
`make verify` must all work.

## 13. Phases, milestones and steps

Every step follows the loop in 0.2 (preview, build, run, teach, check
understanding, record, wait). Milestone numbers (M0 to M9) and test numbers
(1 to 16) refer to the lists in sections 11 and 13. Do not merge or skip steps.
At the end of each phase, do the phase review in 0.8.

### Phase 0: Orientation (no app code yet)

- **S0.1** Ask the student's OS and comfort level (1 to 5) with Python and
  Git. Check or install Python 3.12, Git, `uv` and Docker Desktop.
- **S0.2** Big-picture tour: the diagram in section 3, a story ("one user buys
  one ticket"), and why concurrency is hard (two people click "buy" on the last
  seat at the same instant). No code.
- **S0.3** Python refresher for what we will use: type hints, dicts, classes,
  modules/imports, virtual environments (primer 1, with small exercises).

### Phase A: A working API with users and events (M0, M1)

M0, project skeleton:
- **S0.4** Create the repo, `uv` project and folder layout (explain every folder).
- **S0.5** A "hello" FastAPI app; run it and open `/docs`.
- **S0.6** Settings from `.env` with pydantic-settings.
- **S0.7** Docker Compose with Postgres and Redis; connect from Python.
- **S0.8** `/health/live`, `/health/ready` and the first pytest.
- **S0.9** GitHub Actions running ruff, mypy and pytest.

M1, users and events:
- **S1.1** Database primer; models for users, events, tiers.
- **S1.2** Alembic: the first migration.
- **S1.3** Password hashing and registration (USER role only); test 15.
- **S1.4** Login, JWT access token, and a "current user" dependency.
- **S1.5** Refresh tokens.
- **S1.6** Admin-only event CRUD plus a CLI to create the first admin.
- **S1.7** Paginated event list and search with explicit response models.

### Phase B: Never oversell (M2)

- **S2.1** Race-condition demo: a throwaway script (in `learning/examples/`,
  not in `app/`) doing naive "check, then decrement" with many concurrent
  tasks. Run it and watch it oversell.
- **S2.2** Redis basics and atomic operations; Lua primer; run a tiny Lua
  script by hand in `redis-cli`.
- **S2.3** `reserve_tier.lua`, its Python wrapper and unit tests.
- **S2.4** Hold service and `POST /events/{id}/holds` (no idempotency yet).
- **S2.5** Idempotency-Key handling; test 6.
- **S2.6** Per-user hold cap and request-size limits.
- **S2.7** `release_hold.lua`, `DELETE /holds/{id}` and the expiry sweeper; test 5.
- **S2.8** Missing counter means rehydrate, never zero; test 12.
- **S2.9** The real concurrency test (test 1) with a start barrier; compare
  its result with the S2.1 demo.

### Phase C: A reliable order pipeline (M3, M4)

M3, confirming an order:
- **S3.1** Transactions primer; orders and tickets tables with migrations.
- **S3.2** The mock payment step.
- **S3.3** `consume_hold.lua` and `POST /holds/{id}/confirm` writing the order
  and an outbox row in ONE transaction; tests 2 and 3.

M4, outbox relay and worker:
- **S4.1** Outbox primer; a basic relay using `SKIP LOCKED`.
- **S4.2** Relay retries, backoff and the DEAD state; test 8.
- **S4.3** Redis Streams primer; `XADD`; a worker reading with a consumer group.
- **S4.4** Idempotent processing; test 7, plus the "process it twice" demo.
- **S4.5** Ticket issuing with the DB backstop; test 4, plus the
  "no unique constraint" demo.
- **S4.6** Typed errors, retries, dead letters and inventory release; test 9.
- **S4.7** Relay crash test with the "kill it on purpose" demo; test 10.

### Phase D: Recovery and more features (M5, M6)

- **S5.1** Reconcile logic and the admin endpoint.
- **S5.2** Flush Redis mid-sale and watch recovery; test 11.
- **S5.3** Cancellation through the outbox; test 13.
- **S6.1** Reserved seating: data model and seat-map endpoint.
- **S6.2** `reserve_seats.lua` (all-or-nothing) and its endpoint.
- **S6.3** Seat tests, including double-sell protection.

### Phase E: Hardening and proof (M7, M8)

- **S7.1** Rate limiting; test 14.
- **S7.2** Security hardening checklist (section 9), item by item.
- **S7.3** Live updates with pub/sub and SSE.
- **S8.1** Three API replicas behind nginx.
- **S8.2** Metrics and the Grafana dashboard.
- **S8.3** Locust load test and `verify_consistency.py`.
- **S8.4** Chaos runs: kill the worker, flush Redis; test 16.
- **S8.5** `docs/benchmarks.md` with real, measured numbers.

### Phase F: Stretch (M9), only if the student asks

- Virtual waiting room; OpenTelemetry tracing. Each is its own mini-phase
  with the full loop.

### Final phase: Wrap-up

- Polish README and docs. Run a **mock interview**: ask 15+ questions from
  `docs/interview-notes.md`, one at a time, and give honest feedback.
- Help the student replace "In Progress" on the resume with accurate wording
  and measured numbers only.

## 14. Documentation deliverables

- `README.md`: what it is, architecture diagram, one-command start, results
  (only measured), and what is intentionally out of scope.
- `docs/design.md`: each decision, the alternative considered, and why. Cover
  at least: why Lua for atomicity, why holds with TTL, why an outbox, why
  at-least-once plus idempotency, why DB backstops, why no hot rows.
- `docs/failure-modes.md`: table of Failure | What breaks | How this design
  prevents it | Test name.
- `docs/interview-notes.md`: 15+ likely interview questions with short, honest
  answers about this codebase (including known limitations).
- `docs/learning-log.md`: one entry per step with: date, what was built, the
  key concepts, the student's own one-paragraph summary (written by the
  student), questions they asked, and a **Shaky topics** list.
- `docs/glossary.md`: every technical term, in plain English, with a pointer
  to where it appears in the code.
- `learning/`: the concept primers and runnable examples from 0.5.
- Only list a feature in the README if a test or code path demonstrates it.

## 15. Working agreement

- Follow section 0 on every step. Teaching and checking understanding are part
  of "done"; a step is not finished until the student has passed the gate.
- Keep functions small and typed; add docstrings to tricky parts (Lua wrappers,
  the confirm flow, the sweeper). No TODO-shaped stubs left behind.
- Commit often with clear messages (conventional commits); one logical change
  per commit, and tell the student what each commit contains.
- Ask before adding a dependency, changing the architecture, or deviating from
  any rule in section 4. The tech stack in section 2 does not change.
- Never fabricate results. If a test or benchmark has not been run, say so.
- Never claim a capability the code does not have.
- When unsure whether the student understands, assume they do not yet and
  explain it a different way.
