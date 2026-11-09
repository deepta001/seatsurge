# Learning log

One entry per step. The "In my own words" summary is written by the student.

## Deferred learning

On 2026-11-07, after S0.3, the student decided to skip understanding checks
until the whole project is built ("we'll do the learning part after the
project is done"). Every step from here is recorded as built but not yet
checked. The teach-back for all of them happens at the end.

- S0.3 Python refresher: built and run, not checked.
- S0.4 Repo, uv project and folder layout: built, not checked.
- S0.5 Hello FastAPI app: built, not checked.
- S0.6 Settings from .env: built, not checked.
- S0.7 Docker Compose with Postgres and Redis: built, not checked.
- S0.8 Health endpoints and first pytest: built, not checked.
- S0.9 GitHub Actions CI with ruff, mypy and pytest: built, not checked.
- S1.1 Database models for users, events, tiers: built, not checked.
- S1.2 Alembic and the first migration: built, not checked.
- S1.3 Password hashing and registration (test 15): built, not checked.
- S1.4 Login, JWT access tokens and current-user dependency: built, not checked.
- S1.5 Refresh tokens (stored, rotated, reuse detection): built, not checked.
- S1.6 Admin-only event CRUD and seed_admin CLI: built, not checked.
- S1.7 Paginated public event list and search: built, not checked.
- S2.1 Race-condition (oversell) demo: built, not checked.
- S2.2 Redis basics and first Lua script: built, not checked.
- S2.3 reserve_tier.lua, wrapper and tests: built, not checked.
- S2.4 Hold service and POST /events/{id}/holds: built, not checked.
- S2.5 Idempotency-Key handling (test 6): built, not checked.
- S2.6 Per-user hold cap and request-size limits: built, not checked.
- S2.7 release_hold.lua, DELETE /holds, expiry sweeper (test 5): built, not checked.
- S2.8 Missing counter rehydrated, never zero (test 12): built, not checked.
- S2.9 Concurrency test 1 and 3-process demo: built, not checked.
- S3.1 Transactions primer; orders and tickets tables: built, not checked.
- S3.2 Mock payment provider: built, not checked.
- S3.3 consume_hold.lua and POST /holds/{id}/confirm (tests 2, 3): built, not checked.
- S4.1 Outbox primer and a basic relay using SKIP LOCKED: built, not checked.
- S4.2 Relay retries, backoff and the DEAD state (test 8): built, not checked.
- S4.3 Redis Streams primer; a consumer-group reader: built, not checked.
- S4.4 Idempotent processing (test 7) and the process-twice demo: built, not checked.

## Shaky topics

Topics to revisit in the next phase review.

- **S0.1 environment setup (quiz skipped):** PATH, what Git / uv / Docker each
  do, and why an already-open terminal can't see newly installed tools.
  Bring these questions back in the Phase 0 review.
- **S0.2 big picture (quiz skipped):** the roles of Redis vs Postgres, the
  hold -> confirm -> outbox -> worker story, and why naive "check, then take"
  oversells the last seat. Must be revisited before Phase B (S2.1).

---

## S0.1: Environment setup (2026-11-07)

**What was built:** No code. Installed the tools the project needs on
Windows 11 Home and checked that each one runs.

| Tool | Version | How it was checked |
|---|---|---|
| Python | 3.12.10 (per-user, python.org via winget) | ran a one-line program |
| Git | 2.56.0 (system-wide; the installer asked for admin) | `git --version` |
| uv | 0.13.7 (via winget) | `uv --version`, `uv python find 3.12` |
| Docker Desktop | 4.98.0, engine 29.9.2 | `docker run --rm hello-world` |
| Docker Compose | v5.6.1 | `docker compose version` |

Machine: 8 logical CPUs, 15.5 GB RAM, about 338 GB free on C:.

**Key concepts:** PATH, winget, per-user vs system-wide installs, Docker
client / daemon / image / container.

**Notes for later:**
- Git name and email are not set yet; set them before the first commit
  (S0.4).
- The project folder is inside OneDrive. Consider moving it out (for example to
  `C:\Users\deept\dev\`) before S0.4, so OneDrive doesn't sync or lock the
  `.venv` folder.
- Comfort ratings (Python, Git, Phase 0 confidence): not given yet.

**In my own words:** _(not written; the student used their one "skip the
quiz")_

**Questions the student asked:** none.

**Understanding check:** skipped at the student's request ("move to the
next"). Added to Shaky topics.

---

## S0.2: Big-picture tour (2026-11-07)

**What was built:** No code. Toured the architecture diagram, followed the
"Asha buys one ticket" story, and looked at the last-seat race condition in a
timeline table.

**Key concepts:** Redis as the fast gate vs Postgres as the source of truth,
hold -> confirm, outbox, worker, race condition, check-then-act, atomic,
overselling, thundering herd.

**Comfort ratings:** Python 4. Git and Phase 0 confidence not given yet.

**In my own words:** _(not written; quiz skipped)_

**Questions the student asked:** none.

**Understanding check:** skipped a second time. The student said "no lets skip
the quiz, jump into the code" after being reminded that the rules allow one
skip. Added to Shaky topics.

---

## S0.3: Python refresher (2026-11-07)

**What was built:** `learning/01-python-basics.md` and
`learning/examples/s0_3/` (a `Tier` seat counter plus `main.py`, which imports
it). A break-it demo showed that a type hint doesn't stop `capacity='3'`; the
crash only came later, as a `TypeError`. A demo venv showed `sys.prefix`
changing.

**Key concepts:** type hints, classes, modules and imports, `__name__`,
virtual environments.

**Understanding check:** deferred to the end of the project (see Deferred
learning).

---

## S0.4: Repo, uv project and folder layout (2026-11-07)

**What was built:** the project is named **seatsurge** and moved out of
OneDrive to `C:\Users\deept\dev\seatsurge`. Added:
- A Git repo on the `main` branch, with `.gitignore` and `.gitattributes`
  (LF line endings).
- A bare uv project: `pyproject.toml` (Python 3.12 only), `.python-version`,
  `uv.lock`, and `.venv` created by `uv sync`.
- Packages under `app/`: `api`, `core`, `db`, `redis`, `services`, `worker`.
- Packages under `tests/`: `unit`, `integration`, `concurrency`,
  `adversarial`.
- A `README.md` with the planned architecture and the folder table.

**Key concepts:** Git repository, staging, lockfile, packages
(`__init__.py`), line endings (LF vs CRLF).

**Understanding check:** deferred to the end of the project.

---

## S0.5: Hello FastAPI app (2026-11-07)

**What was built:**
- Added `fastapi` and `uvicorn` with `uv add`. They pulled in pydantic,
  starlette and anyio, plus `opentelemetry-api`, which FastAPI itself
  depends on.
- `app/main.py` creates the `FastAPI` app with one route, `GET /`, which
  returns `{"message": "Hello from seatsurge"}`.
- `learning/02-http-basics.md` covers methods, status codes, JSON and REST.

**Ran it:** `uv run python -m uvicorn app.main:app --port 8000`.
- `GET /` returned 200 with the hello JSON.
- An unknown path returned 404.
- `/docs` showed the Swagger UI with the `GET /` route.

**Debugging moment:** `uv run uvicorn ...` failed with "An Application Control
policy has blocked this file". Windows Smart App Control blocks the unsigned
`uvicorn.exe` launcher in `.venv\Scripts`. Running it as `python -m uvicorn`
works, and the security setting was left alone.

**Key concepts:** HTTP, methods, status codes, JSON, REST, routes, FastAPI,
uvicorn, ports, `async def`, OpenAPI/Swagger.

**Not yet tested automatically:** the first pytest comes in S0.8.

**Understanding check:** deferred to the end of the project.

---

## S0.6: Settings from .env (2026-11-07)

**What was built:**
- Added `pydantic-settings`, which brings `python-dotenv` with it.
- `app/core/settings.py` has a typed `Settings` class (`app_name`,
  `environment`, `database_url`, `redis_url`) and a cached `get_settings()`.
- `app/main.py` now takes its title from the settings.
- `.env.example` is the committed template. `.env` is private: its passwords
  were generated by a script and never printed, and Git ignores the file.

**Ran it:**
1. Normal load: the secrets print as `**********`.
2. `$env:ENVIRONMENT='production'` overrode the `.env` value.
3. `ENVIRONMENT=banana` gave a `ValidationError` (literal_error).
4. Running from a folder with no `.env` gave a `ValidationError` naming the
   two missing fields.
5. `app.main` still imports, with title `seatsurge`.

**Worth remembering:** `env_file=".env"` is relative to the folder you run
from, which is why demo 4 failed outside the project folder.

**Key concepts:** environment variables, `.env` vs `.env.example`,
validation, fail fast, `SecretStr`, `Literal`, `@lru_cache`.

**Not yet tested automatically:** pytest arrives in S0.8.

**Understanding check:** deferred to the end of the project.

---

## S0.7: Docker Compose with Postgres and Redis (2026-11-07)

**What was built:**
- `docker-compose.yml` runs `postgres:16-alpine` and `redis:7-alpine`:
  - The passwords come from `.env`, and Compose refuses to start if they're
    missing.
  - Redis has `--requirepass`.
  - Ports are bound to 127.0.0.1 only.
  - The Postgres data lives in the `postgres-data` named volume.
  - Both services have healthchecks.
- Added `sqlalchemy[asyncio]` (2.1.8, the same 2.x API as 2.0), `asyncpg` and
  `redis` (the 8.1 client library, talking to Redis server 7.4).
- `app/db/session.py` has `create_db_engine()`, and `app/redis/client.py`
  has `create_redis_client()`.
- `scripts/check_connections.py` connects to both and prints the versions.

**Ran it:**
1. `docker compose up -d --wait`: both services reported healthy.
2. The check printed `Postgres OK: server version 16.15` and
   `Redis OK: server version 7.4.12, read back 'world'`.
3. Break-it, wrong Redis password: `AuthenticationError`.
4. Break-it, Redis stopped: `ConnectionError` (connection refused).
5. After restarting Redis, the check passed again.

**Key concepts:** Compose services, volumes, port mapping, healthchecks,
SQLAlchemy engine, connection pool, async Redis client, TTL.

**Not yet tested automatically:** pytest arrives in S0.8.

**Understanding check:** deferred to the end of the project.

---

## S0.8: Health endpoints and the first pytest (2026-11-07)

**What was built:**
- `app/main.py` has a `lifespan` that creates the engine and Redis client
  once at startup, keeps them on `app.state`, and closes them at shutdown.
- `app/api/dependencies.py` has `get_db_engine` and `get_redis`.
- `app/api/health.py` has two routes:
  - `GET /health/live` always returns `{"status":"ok"}`.
  - `GET /health/ready` runs `SELECT 1` and `PING` concurrently, each with a
    2s timeout. It returns 200 `ready`, or 503 `not_ready` with an
    `ok`/`unavailable` per service. The error details go only to the log.
- The dev dependencies `pytest` and `httpx` were added; the student approved
  httpx, which isn't in the stack list.
- `tests/conftest.py` points the tests at port 1. `tests/unit/test_health.py`
  has 4 tests, and pytest is configured in `pyproject.toml`.

**Ran it:**
- `uv run python -m pytest -v` passed all 4 tests. There's 1 warning:
  Starlette says using httpx with its TestClient is deprecated in favour of
  `httpx2`. This was left as is for now.
- Live against Docker: ready returned 200; with Redis stopped it returned
  503 (`redis: unavailable`) while live stayed 200; after restarting Redis it
  returned 200 again.

**Debugging moment, a real bug found by the live demo:** `/health/ready`
returned 503 even with both services up, because both checks hit the 2s
timeout. On Windows, `localhost` resolves to `::1` (IPv6) first. Docker only
listens on 127.0.0.1, and Windows takes about 2s to give up on `::1` before
trying 127.0.0.1. Measured: `localhost` took 2.03s, `127.0.0.1` took 0.00s.
The S0.7 check script had passed only because it had no timeout; it was
quietly slow. Fix: both URLs in `.env.example` and `.env` now use 127.0.0.1.
**Lesson:** mocked unit tests can't catch environment bugs; that's why we
also run against the real services (and why integration tests come later).

**Key concepts:** liveness vs readiness, 503, lifespan, `app.state`, FastAPI
dependencies, routers, response models, timeouts, `gather`, pytest
fixtures, conftest, monkeypatch, TestClient.

**Understanding check:** deferred to the end of the project.

---

## S0.9: GitHub Actions CI (2026-11-07)

**What was built:**
- The dev dependencies `ruff` and `mypy`, configured in `pyproject.toml`:
  - ruff: line length 100; rule sets E, W, F, I, B and UP; `Depends`
    allowed in defaults.
  - mypy: checks `app`, `tests` and `scripts`; every function must be typed;
    `strict` on `app.services.*`.
- `.github/workflows/ci.yml` runs on each push to `main` and on every pull
  request. It runs `uv sync --locked`, ruff check, ruff format --check, mypy
  and pytest on ubuntu-latest, with read-only permissions.

**Ran it:**
- The first ruff run found 2 lines that were too long, plus 1 primer snippet
  to reformat; all fixed. The first mypy run found no issues.
- CI simulation: copied only the files Git would push (no `.env`, no `.venv`)
  into a clean folder, ran `uv sync --locked`, and every step passed
  (4 tests).
- Break-it: mypy caught `Tier("floor", capacity="3")` before running it
  ("incompatible type 'str'; expected 'int'"). That's the bug Python itself
  only caught at runtime in S0.3.

**On GitHub (2026-11-08):** the repo was pushed to
https://github.com/deepta001/seatsurge. The push needed the student's GitHub
sign-in through Git Credential Manager, run in their own terminal. The first CI
run passed on commit 61dbc26:
https://github.com/deepta001/seatsurge/actions/runs/42498929501

**Key concepts:** linter vs formatter vs type checker, CI, workflows / jobs /
steps, locked installs.

**Understanding check:** deferred to the end of the project.

---

## S1.1: Database models for users, events and tiers (2026-11-08)

**What was built:**
- `app/db/base.py`: `Base` (DeclarativeBase) with a constraint naming
  convention, so names are predictable (for example
  `ck_tiers_sold_within_capacity`).
- `app/db/models.py`:
  - `User`: email and username UNIQUE; `role` defaults to USER in both Python
    and the DB; `created_at` set by the DB.
  - `Event`: seating and status restricted; status defaults to DRAFT;
    `created_by` is a foreign key to users with no cascade.
  - `Tier`: UNIQUE(event_id, name); CHECKs for capacity > 0,
    0 <= sold <= capacity (the oversell backstop), price_cents >= 0 and
    next_number >= 0; sold and next_number default to 0.
  - Status fields are stored as text plus a CHECK (`native_enum=False`)
    instead of Postgres enum types, which are awkward to migrate.
- `tests/unit/test_models.py`: 8 tests on the generated SQL, run without a
  database.
- `learning/examples/s1_1/constraints_demo.py`: creates the tables in a
  throwaway schema inside one transaction, tries to break each rule, then
  rolls back.
- No tables exist in the real database yet; Alembic creates them in S1.2.

**Ran it:**
- 8/8 model tests passed.
- The demo allowed selling 2 of 2 seats, then rejected each rule-break with
  the right constraint: sold > capacity, capacity 0, a duplicate tier name, a
  duplicate username, role SUPERADMIN, a missing creator (FK), and deleting
  the creator (FK). The `demo_s1_1` schema was gone afterwards, and `public`
  still has 0 tables.

**Debugging moments:**
1. Docker Desktop wasn't running after a restart (`ConnectionRefusedError`).
   Starting it and running `docker compose up -d --wait` fixed it.
2. A mistake in the demo itself: the setup rows were inserted with
   hand-written `id = 1`, but the SERIAL counter didn't advance. The next
   insert also got id 1 and hit `pk_users` / `pk_events` before the intended
   rule. The fix was to let Postgres assign ids. Lesson: never hand-pick
   SERIAL ids.

**Key concepts:** tables, primary and foreign keys, NOT NULL, UNIQUE, CHECK,
server defaults, transactions and rollback, savepoints, ORM models, integer
cents, timezone-aware timestamps.

**Understanding check:** deferred to the end of the project.

---

## S1.2: Alembic and the first migration (2026-11-08)

**What was built:**
- Added `alembic` (1.20) and ran `alembic init -t async migrations`.
- `alembic.ini`:
  - Date-prefixed migration file names.
  - No `sqlalchemy.url`, so no password is ever committed.
  - ruff format and fix run on each new migration through the `module`
    runner, which Smart App Control allows.
- `migrations/env.py` was rewritten:
  - Reads DATABASE_URL via `get_settings()`.
  - `target_metadata = Base.metadata`, after importing the models.
  - `compare_server_default=True`; NullPool; supports offline `--sql` mode.
- `migrations/script.py.mako` was tidied to modern type hints with no
  trailing whitespace.
- First migration `19624396e697`, "create users events tiers": autogenerated,
  then reviewed by hand before applying.
- CI got a `postgres:16-alpine` service plus three steps: `upgrade head`,
  `alembic check`, then `downgrade base` followed by `upgrade head`.
- mypy now also checks `migrations/`.

**Ran it:**
- `upgrade head` created users, events, tiers and `alembic_version`. All 12
  constraint names match the naming convention, including the enum CHECKs
  (`ck_users_user_role` and so on).
- `alembic check` reported "No new upgrade operations detected".
- `downgrade base` left 0 app tables; `upgrade head` brought back 3.
- Real-DB backstop: inserting a tier with sold=3 > capacity=2 was rejected by
  `ck_tiers_sold_within_capacity` (inside a rolled-back transaction).
- Break-it: adding a `discount_cents` column to `Tier` in memory made
  `alembic check` fail and name the missing `add_column`.

**Small hiccup:** the first post-write hook ran `ruff check` before
`ruff format`, so it reported long lines that formatting would have wrapped.
Swapping the order fixed it.

**Key concepts:** migrations vs create_all, revisions and their chain,
head/base, autogenerate (a draft to review), drift and `alembic check`,
reversible downgrades.

**Understanding check:** deferred to the end of the project.

---

## S1.3: Password hashing and registration (2026-11-08)

**What was built:**
- Added `argon2-cffi`, plus the dev libraries `pytest-asyncio` and
  `testcontainers` (all in the stack).
- `app/core/security.py`: `hash_password` and `verify_password` (argon2id).
- `app/core/errors.py`: `DomainError` and `UserAlreadyExists` (409).
  `app/api/errors.py` turns DomainErrors into
  `{"error": code, "message": safe text}`.
- `app/db/session.py`: `create_session_factory()`. `app/main.py` creates it
  in lifespan, and `get_db_session` gives one session per request.
- `app/services/auth.py`: `register_user()`.
  - It has no role parameter and always creates USER.
  - Email is lower-cased.
  - No check-then-insert: the UNIQUE constraint decides, and only
    `uq_users_email` / `uq_users_username` become UserAlreadyExists.
    Anything else re-raises.
- `app/api/auth.py`: `POST /auth/register`.
  - `RegisterRequest` uses `extra="forbid"` and accepts an email of the shape
    a@b.c, a username of 3 to 50 safe characters, and a password of 12 to 128
    characters.
  - `UserResponse` never includes the hash.
- Real-database tests: `tests/conftest.py` starts a testcontainers
  Postgres 16 per run, migrates it with Alembic, overrides `get_db_session`,
  uses httpx `ASGITransport`, and truncates the tables after each test.
  `migrations/env.py` accepts a passed-in URL for this.
- Tests: `tests/unit/test_security.py` (5),
  `tests/integration/test_register.py` (6), and
  `tests/adversarial/test_15_...` (4).
- `docs/failure-modes.md` was started, with test 15 and the sign-up race.

**Ran it:**
- 27/27 tests passed on the first run (about 14s, including starting the
  container). The race test released 10 sign-ups for one email at once with
  a start barrier: exactly 1 got 201 and 9 got 409, leaving 1 row.
- Live against the dev DB:
  - Register: 201, with the email lower-cased.
  - Duplicate: 409 with a clean body.
  - `"role":"ADMIN"`: 422 `extra_forbidden`.
  - The DB row has role USER and an `$argon2id$` hash.
  - The demo rows were deleted afterwards.
- A hash takes about 55 ms on this laptop (slow on purpose).

**Note:** the demo user got id 2, because the rolled-back insert in S1.2
had already used id 1. Sequences never go backwards, even on rollback.

**Key concepts:** one-way hashing, argon2, salt, typed domain errors,
DB-enforced uniqueness vs check-then-insert, sessions, integration tests
with testcontainers, start barriers.

**Understanding check:** deferred to the end of the project.

---

## S1.4: Login, JWT access tokens and the current-user dependency (2026-11-08)

**What was built:**
- Added `pyjwt` (stack).
- Settings: `jwt_secret_key` (SecretStr, at least 32 characters, required)
  and `access_token_minutes` (default 15). A 64-character secret was
  generated into `.env` without being printed. `.env.example`, the test
  conftest and CI each have their own key.
- `app/core/tokens.py`:
  - `create_access_token` puts `sub`, `role`, `type=access`, `iat` and `exp`
    in the token.
  - `decode_access_token` pins HS256, requires all those claims, checks the
    type, and maps every failure to `NotAuthenticated`.
- `app/core/errors.py`: `InvalidCredentials` and `NotAuthenticated` (401 with
  `WWW-Authenticate: Bearer`). The error handler now passes headers through.
- `app/services/auth.py`: `authenticate_user`, which uses a dummy-hash check
  for unknown emails so the timing matches a wrong password.
- `app/api/dependencies.py`: `get_current_user`, built on HTTPBearer, which
  returns `AccessTokenClaims` with **no DB query**.
- Routes: `POST /auth/login` returns `{access_token, token_type, expires_in}`;
  `GET /me` (`app/api/me.py`) is the first protected route.
- Tests:
  - `tests/unit/test_tokens.py` (8): round trip, a 15-minute lifetime,
    expired, a tampered payload, a wrong key, `alg: none`, a refresh-type
    token, and junk.
  - `tests/unit/test_me.py`: `/me` returns 200 while the DB is unreachable,
    which proves there's no DB hit.
  - `tests/integration/test_login.py` (5).

**Ran it:**
- 41/41 tests passed; ruff and mypy are clean.
- Live demo against the dev DB:
  - Login: 200 with `expires_in` 900.
  - The decoded payload is readable.
  - `/me`: 200.
  - Editing role to ADMIN: 401. A 16-minute-old token: 401.
  - Median login time: 73 ms for a wrong password vs 74 ms for an unknown
    email.
  - The demo user was deleted afterwards.

**Documented trade-off:** with no DB check, a deleted or demoted user's token
works until it expires (at most 15 minutes).

**Not yet:** login rate limiting (S7.1) and refresh tokens (S1.5).

**Key concepts:** JWT structure, signing vs encrypting, claims (`sub`, `exp`,
`iat`), algorithm pinning, bearer auth, stateless auth and its trade-off,
user-enumeration defence, timing side channels.

**Understanding check:** deferred to the end of the project.

---

## S1.5: Refresh tokens (2026-11-08)

**Decision (the student chose it):** stored, rotated refresh tokens with
reuse detection, rather than a stateless JWT refresh. This adds a
`refresh_tokens` table that isn't in the CLAUDE.md schema; it's recorded in
`docs/design.md`.

**What was built:**
- `RefreshToken` model, plus migration `7e7b636c3319`:
  - Columns: id (bigint), user_id (FK, CASCADE, indexed), token_hash
    (UNIQUE, 64), family_id (uuid, indexed), expires_at, created_at,
    used_at, revoked_at.
- Setting: `refresh_token_days` (default 7).
- `app/services/refresh_tokens.py`:
  - `issue_refresh_token` creates a new family.
  - `rotate_refresh_token` claims the token with one conditional UPDATE ...
    RETURNING, re-reads the user, and issues a replacement in the same
    family. On failure it revokes the family if the token had been used.
  - `revoke_refresh_token_family` handles logout.
- Routes:
  - `/auth/login` now also returns `refresh_token` and `refresh_expires_in`.
  - New `POST /auth/refresh`.
  - New `POST /auth/logout` (always 204).
- `tests/integration/test_refresh.py` (10 tests), including reuse detection,
  expiry, logout, a role change at refresh, and a 5-way race. The test
  cleanup also truncates `refresh_tokens`.
- `docs/design.md` was started, with all decisions so far.

**Ran it:**
- 51/51 tests passed (the race gave exactly [200, 401, 401, 401, 401]).
  ruff, mypy and `alembic check` are clean.
- Live: R1 → R2 → R3 refreshed fine. Replaying R1 gave 401, and R3 then gave
  401 too. The DB showed all 3 rows in one family marked revoked. Deleting
  the demo user cascaded its tokens (0 rows left).

**Small fixes:** a docstring 1 character too long, and the test helper was
typed `dict[str, str]` although the response holds a number (mypy caught
it).

**Known gaps:** no cleanup of old token rows yet; logout doesn't end the
current access token (it expires within 15 minutes).

**Key concepts:** refresh vs access tokens, token rotation, token families
and reuse detection, hashing high-entropy secrets with SHA-256, conditional
UPDATE ... RETURNING as an atomic claim, ON DELETE CASCADE.

**Understanding check:** deferred to the end of the project.

---

## S1.6: Admin-only event CRUD and the admin CLI (2026-11-08)

**What was built:**
- Errors: `Forbidden` (403), `EventNotFound` (404),
  `InvalidEventStatusChange` (409) and `EventNotDeletable` (409).
- `require_admin` dependency: token role must be ADMIN, with no DB query.
- `app/services/events.py`:
  - `create_event`: a DRAFT event plus its tiers in one transaction, using
    `flush` to get the event id.
  - `update_event`: partial update with one-way status rules; locks the row
    `FOR UPDATE`.
  - `delete_event`: DRAFT only; deletes tiers first, then the event.
- `app/api/events.py`: `POST /events` (201), `PATCH /events/{id}` and
  `DELETE /events/{id}` (204), with explicit request and response models.
  - Validation: `AwareDatetime` in the future, 1 to 20 tiers with unique
    names, capacity 1 to 100,000, `extra="forbid"`, and an empty PATCH is
    rejected.
- `app/services/auth.py`: `create_admin`, sharing a private `_create_user`
  with `register_user` (which still has no role parameter).
- `scripts/seed_admin.py`: `--email` and `--username`, a password via
  getpass twice or `SEATSURGE_ADMIN_PASSWORD`, at least 12 characters.
  `scripts/__init__.py` was added (mypy saw the module under two names
  without it).
- Tests: `tests/integration/test_events_admin.py` (17, including 7
  parametrised validation cases) and `tests/unit/test_seed_admin.py` (3).

**Ran it:**
- 70/70 tests passed; ruff, mypy and `alembic check` are clean.
- Live against the dev DB:
  - The CLI created demo_admin (ADMIN), and `/me` showed role ADMIN.
  - A regular user's POST /events got 403.
  - The admin got 201 DRAFT, then published it.
  - DELETE of the published event got 409 `event_not_deletable`.
  - Cancelling worked; re-publishing got 409 `invalid_status_change`.
  - All demo rows were deleted afterwards.

**Small fixes:** mypy's "source file found twice" error (fixed by adding
`scripts/__init__.py`), and a test patching `getpass` through the CLI module
(now patches the `getpass` module directly).

**Not yet:** public GET routes (S1.7); tier edits (they wait for Redis
inventory).

**Key concepts:** authorisation vs authentication (403 vs 401), role checks,
state machines, `flush` vs `commit`, `SELECT ... FOR UPDATE`, transactions
spanning several rows, CLIs with argparse and getpass, parametrised tests.

**Understanding check:** deferred to the end of the project.

---

## S1.7: Paginated public event list and search (2026-11-08)

**What was built:**
- `app/services/events.py`:
  - `list_upcoming_events`: PUBLISHED and `starts_at > now`, optional
    `query` (ILIKE contains, escaped) and `city` (case-insensitive equality),
    ordered by `starts_at, id`, with limit/offset plus a total count.
  - `get_public_event`: PUBLISHED or CANCELLED; a DRAFT raises
    EventNotFound.
  - `contains_pattern` escapes `\`, `%` and `_`.
- `app/api/events_public.py` (new, keeping the admin file under 200 lines):
  - `GET /events` returns an `EventList` of `EventSummary` items with
    total, limit and offset. Limits: limit 1 to 100, offset 0 to 10,000.
  - `GET /events/{id}` returns an `EventDetail` with tiers and no
    `created_by`.
- Tests: `tests/integration/test_events_public.py` (12) and
  `tests/unit/test_search_pattern.py` (2).

**Ran it:**
- 84/84 tests passed; ruff and mypy are clean.
- Live: the list showed only the 2 upcoming published events, soonest
  first. `city=leeds` filtered correctly; `query=%` returned nothing; the
  detail page has no `created_by`; the draft gave 404. The demo rows were
  cleaned up.

**Debugging moment:** ruff W605 flagged `"\%"` in the escape helper. Writing
the code through a shell heredoc lost one of the doubled backslashes. It
worked by accident (Python keeps unknown escapes), but it's deprecated and
fragile; it was rewritten with a `LIKE_ESCAPE` constant.

**Key concepts:** public vs internal response models, limit/offset paging and
stable ordering, ILIKE and wildcard escaping, visibility rules, query caps.

**Understanding check:** deferred to the end of the project.

**Phase A (M0 + M1) is now built.** The phase review (CLAUDE.md 0.8) is next.

---

## Phase A review: accounts and events (2026-11-08)

**Done (CLAUDE.md 0.8):**
1. **Demo:** a 16-step end-to-end run over real HTTP against Docker Postgres
   and Redis:
   - Readiness check 200.
   - Asking for ADMIN at sign-up: 422. Normal sign-up: 201 as USER, with
     the email lower-cased.
   - Wrong password: 401. Login: 200 (900 s). `/me`: 200.
   - A user creating an event: 403. An admin: 201 DRAFT.
   - Public GET of the draft: 404. After publishing, search finds it, and
     the detail page shows both tiers.
   - Refresh: 200. Replaying the old token: 401, and the newest token: 401
     (family revoked).
   - Deleting the published event: 409.
   - Afterwards 0 users, 0 events and 0 refresh tokens were left.
2. **Recap diagram:** a Mermaid diagram of the Phase A architecture in
   README.md.
3. **Quiz:** deferred. The student chose to do all learning at the end of the
   project.
4. **Teach-back:** deferred, for the same reason.
5. **README** was rewritten: a status banner, a feature table with the test
   proving each feature, the current vs target architecture, a quick start,
   and known limitations. `docs/design.md` already covered every Phase A
   decision.
6. **CV wording:** suggested in the session, limited to built and tested
   facts.

**Measured facts available for a CV:** 84 automated tests (31 unit, 49
integration, 4 adversarial) running against real Postgres; CI with
lint, types, tests and migration checks; a 10-way concurrent sign-up race
gives exactly 1 account; a 5-way concurrent refresh with one token gives
exactly 1 success; login timing is 73 ms for a wrong password vs 74 ms for
an unknown email.

**For the end-of-project learning review (carry forward):**
- The Shaky topics from S0.1 and S0.2 (both quizzes were skipped).
- Every Phase A step S0.3 to S1.7 is in "Deferred learning".
- Suggested teach-back for Phase A: "Walk through what happens, layer by
  layer, from `POST /auth/login` to a successful `GET /me`, and explain why
  `/me` never queries the database."

---

## Phase B starts. S2.1: Race-condition demo (2026-11-08)

**What was built:** `learning/examples/s2_1/oversell_demo.py`, a deliberately
broken, throwaway script (never app code). 1,000 buyers, 100 seats, a start
barrier, and naive check-then-take, in two versions: in memory (with a small
`asyncio.sleep` in the gap) and against real Redis (`GET` then `DECR`).
Primer: `learning/11-race-conditions-and-atomicity.md`.

**Ran it (measured):**
- In memory: sold 1,000 of 100, counter -900, in every run.
- Real Redis: oversold in 11 of 13 runs, by 1 to 41 seats, and the counter
  went negative. Two runs happened to come out right, which shows how
  intermittent the bug is.
- 10 buyers on 5 seats: oversold 5 in every run, in both modes.
- 1 buyer, 1 seat: always fine.

**Debugging moment:** the first Redis run crashed with
`MaxConnectionsError: Too many connections`. redis-py's default async pool
raises instead of waiting when 1,000 requests arrive at once. The demo now
uses a `BlockingConnectionPool(max_connections=50)`. The app's own client
needs the same treatment (recorded in `docs/design.md` for S2.3/S2.4).

**Key concepts:** race condition, check-then-act, stale reads, intermittent
bugs, atomicity, why per-process locks don't work across replicas.

**Comfort check for Phase B:** not asked (learning deferred).

**Understanding check:** deferred to the end of the project.

---

## S2.2: Redis basics, atomic operations and a first Lua script (2026-11-08)

**What was built:**
- A hands-on `redis-cli` tour of the types CLAUDE.md section 5 uses:
  - Counters (`SET`, `DECRBY`, `INCR`).
  - `GET` on a missing key returns nil, not 0.
  - TTL (`SET ... EX 2` deleted itself; `TTL` went 1, then -2).
  - Hash (a hold record), sorted set (`ZRANGEBYSCORE` by expiry), set (a
    duplicate is ignored; `SISMEMBER`).
- `learning/examples/s2_2/take_seats.lua`: take N only if N are left;
  returns 1, 0, or -2 for a missing counter.
- Run by hand with `redis-cli --eval`:
  - Take 2 of 3 returned 1 (1 left). Take 2 more returned 0 and changed
    nothing.
  - Take the last 1 returned 1 (0 left). A missing counter returned -2.
  - Also loaded by SHA (`SCRIPT LOAD` / `EVALSHA`).
- The S2.1 demo gained `--mode lua` (uses `register_script`), and the
  default is now `all`.
- Primers: `learning/10-redis-data-types-and-ttls.md` and
  `learning/12-lua-scripts-in-redis.md`.

**Ran it (measured, 1,000 buyers on 100 seats):**
- 5 side-by-side runs: memory oversold 900 every run; naive Redis oversold
  2 to 43; Lua sold exactly 100 with the counter at 0 every run.
- Lua alone: 10 more runs, all exactly 100. With 5,000 buyers: 2 runs, both
  exactly 100.

**Debugging moments:**
1. In PowerShell, `R` is a built-in alias for `Invoke-History`, so a helper
   function named `R` never ran. The tour was moved to Bash.
2. Git Bash rewrote `/tmp/take_seats.lua` into a Windows path before it
   reached the container. `MSYS_NO_PATHCONV=1` fixed it.

**Key concepts:** Redis data types, TTL and self-expiring keys, missing is
not zero, single-command atomicity, Lua scripts as atomic multi-step
operations, KEYS vs ARGV, EVAL vs EVALSHA, return codes.

**Understanding check:** deferred to the end of the project.

---

## S2.3: reserve_tier.lua, its Python wrapper and tests (2026-11-08)

**What was built:**
- `app/redis/lua/reserve_tier.lua` follows the section 5 sketch, plus an
  `event` field in the hold hash. Order of checks: missing counter (-2),
  user cap (-3), not enough seats (-1). Only then: DECRBY inventory, INCRBY
  uhold, HSET hold, EXPIRE hold (TTL + 900), ZADD `holds:expiry`. Returns 1.
- `app/redis/keys.py`: one function per key in the schema.
- `app/redis/scripts.py`:
  - `ReserveOutcome` enum and `HoldRequest` dataclass.
  - `ReserveTierScript` uses `register_script` (EVALSHA) and refuses
    qty < 1 before calling Redis.
- `app/redis/client.py`: the S2.1 pool problem is fixed.
  `build_redis_client` uses a `BlockingConnectionPool`
  (`redis_max_connections` = 50, `redis_pool_timeout_seconds` = 5; new
  settings) and `Redis.from_pool`, so `aclose()` also closes the pool.
- `tests/conftest.py`: a Redis 7 testcontainer plus a `redis` fixture built
  with the app's `build_redis_client`; FLUSHDB after each test.
- Tests: `tests/integration/test_reserve_tier.py` (9) and
  `tests/unit/test_redis_keys.py` (1).
  - Every refusal is compared against a before/after snapshot (nothing
    changed).
  - The race test: 500 buyers wanting 1 to 3 seats each, on 50 seats.

**Ran it:**
- 94/94 tests passed; the new Redis tests passed 3 runs in a row (the race
  test uses random quantities); ruff and mypy are clean.

**Debugging moment:** the race test first failed with the same
`MaxConnectionsError` as S2.1, because the test fixture used a default pool.
The fix was for tests to use the app's own client builder, so the test now
also proves the pool fix.

**Key concepts:** one script for a whole multi-key update, validate-then-
write, return codes mapped to an enum, EVALSHA via `register_script`,
blocking connection pools, snapshot assertions for "nothing changed".

**Understanding check:** deferred to the end of the project.

---

## S2.4: Hold service and POST /events/{id}/holds (2026-11-08)

**What was built:**
- Settings: `hold_ttl_seconds` (300) and `hold_user_cap` (10).
- Errors: TierNotFound 404, EventNotOnSale 409, SeatingNotSupported 422,
  SoldOut 409, HoldLimitExceeded 409, and InventoryNotReady 503 with
  `Retry-After: 1`.
- `app/redis/scripts.py` now reads the Lua text once at import.
- `app/services/holds.py`:
  - `create_hold` checks the event is published, upcoming and general
    admission, and that the tier belongs to it (Postgres).
  - It then runs `ReserveTierScript` with a new uuid4 hold id and an expiry
    of now + TTL.
  - It maps each outcome to a typed error.
- `app/api/holds.py`: `POST /events/{event_id}/holds` with body
  `{tier_id, quantity 1-10}` (`extra="forbid"`). It needs a login and
  returns 201 `{hold_id, event_id, tier_id, quantity, expires_at}`.
- `tests/integration/test_holds_api.py` (10 tests), using real Postgres and
  real Redis (`get_redis` overridden). The race test signs tokens for 300
  made-up user ids, which works because auth is stateless.

**Ran it:**
- 104/104 tests passed; ruff and mypy are clean.
  - The 300-buyer HTTP race gave exactly 50 x 201 and 250 x 409 sold_out,
    with the counter at 0.
- Live against the dev stack:
  - Missing counter: 503 with Retry-After 1.
  - User 1 held 2 (201). User 2 wanted 2 with 1 left: 409. User 2 took 1
    (201). User 3: 409.
  - Redis showed 0 left and a correct hold record.
  - Everything was cleaned up (0 Redis keys, 0 rows).

**Known gaps:** no idempotency yet (S2.5); holds don't release seats yet
(S2.7); the counter isn't rebuilt automatically yet (S2.8).

**Key concepts:** layered checks (DB for sellability, Redis for
availability), user identity from the token only, mapping outcomes to HTTP
status codes, 503 + Retry-After, HTTP-level concurrency tests.

**Understanding check:** deferred to the end of the project.

---

## S2.5: Idempotency-Key handling, test 6 (2026-11-08)

**What was built:**
- `app/services/idempotency.py`:
  - `request_fingerprint` is SHA-256 of canonical JSON (route + body).
  - `begin` claims with SET NX EX 30, or replays the stored answer, or raises
    IdempotencyKeyReused (422) / RequestInProgress (409, Retry-After 1).
  - `complete` stores `{state: done, fingerprint, status_code, body}` for
    24 h. `abandon` deletes the claim.
- `app/api/holds.py`: the `Idempotency-Key` header is required (8 to 100
  characters, `[A-Za-z0-9_-]`).
  - A replay returns the stored JSON with `Idempotent-Replayed: true`.
  - A 4xx DomainError is stored; a 5xx error or any other exception
    abandons the claim.
- `app/redis/keys.py`: `idempotency_key(user, key)`.
- Tests:
  - The shared sale fixtures moved to `tests/sales.py` (loaded via
    `pytest_plugins`), and the hold helper sends a fresh key.
  - New: `tests/adversarial/test_06_same_idempotency_key_creates_one_hold.py`
    (7 tests) and `tests/unit/test_idempotency_fingerprint.py` (2).

**Ran it:**
- 113/113 tests passed; ruff and mypy are clean.
- Test 6 passed 5 runs in a row (it includes 10 simultaneous retries with
  one key: exactly one hold, one seat taken).

**Key concepts:** idempotency, idempotency keys, request fingerprints, SET NX
as an atomic claim, which outcomes to store (final vs temporary), crash
windows, at-most-once vs exactly-once thinking.

**Understanding check:** deferred to the end of the project.

---

## S2.6: Per-user hold cap and request-size limits (2026-11-08)

**What was built:**
- `app/api/body_limit.py`: `BodySizeLimitMiddleware` (raw ASGI), added as
  the outermost middleware.
  - A declared Content-Length that is too big or not a number gets 413 at
    once.
  - Otherwise it reads the body itself, stops past the limit, and replays
    the body to FastAPI as one message.
- New setting: `max_request_body_bytes` (16 KB).
- Tests:
  - `tests/unit/test_body_limit.py` (4): declared oversized, chunked with no
    length, garbage Content-Length, and a normal body still gets through.
  - `tests/concurrency/test_user_hold_cap.py` (3 parametrised cases): one
    user firing 20 x 1, 8 x 3 or 3 x 10 seats at once ends at exactly 10, 9
    and 10 held. Every refusal is `hold_limit_exceeded`, and Redis agrees.

**Ran it:**
- 120/120 tests passed; the concurrency tests passed 3 runs in a row; ruff
  and mypy are clean.
- Live with uvicorn: a 200-byte body reached validation (422); a 1 MB body
  got 413 in 1 ms.

**Debugging moment:** the first middleware raised its "too large" signal
from inside the app's `receive()`. FastAPI wraps body parsing in a broad
`except` and turned it into a 400 "error parsing the body". The redesign
reads the body in the middleware first (it's at most 16 KB) and replays it,
so the 413 decision never passes through FastAPI.

**Key concepts:** ASGI middleware, the receive/send messages, Content-Length
vs chunked transfer, 413 Payload Too Large, defence in depth (pydantic field
limits plus a body cap plus the atomic cap in Redis).

**Understanding check:** deferred to the end of the project.

---

## S2.7: release_hold.lua, DELETE /holds/{id} and the expiry sweeper, test 5 (2026-11-08)

**What was built:**
- `app/redis/lua/release_hold.lua` (an idempotent release):
  - Returns: 1 released, 0 already finished, -1 not found, -2 not the
    owner, -3 not expired (sweeper mode), -4 keys mismatch.
  - Only a HELD hold gives its seats back.
  - It never creates a missing counter, and never lets uhold go negative.
- `reserve_tier.lua`: uhold now gets EXPIRE TTL + 900 (a safety net).
- `app/redis/scripts.py`:
  - `ReleaseOutcome`, `HoldStatus` and `ReleaseHoldScript`.
  - It reads the hold first to build the keys; the script re-checks them.
- `app/services/holds.py`: `cancel_hold` maps not-found and not-owner both
  to `HoldNotFound` (404).
- `app/api/holds.py`: `DELETE /holds/{hold_id}` returns 204, including for
  an already-released hold.
- `app/worker/sweeper.py`: `sweep_expired_holds(now=...)` and
  `run_sweeper` (a 1 s loop that survives errors).
- `app/worker/main.py`: the worker process entry point.
- Tests:
  - `tests/integration/test_release_hold.py` (9).
  - `tests/integration/test_cancel_hold_api.py` (5).
  - `tests/adversarial/test_05_abandoned_hold_returns_inventory.py` (4):
    the sweeper is given "now", so the tests don't wait.

**Ran it:**
- 138/138 tests passed; the race tests passed 3 runs in a row; ruff and
  mypy are clean. All 18 new tests passed on the first run.
- Live, with real time: the API ran with `HOLD_TTL_SECONDS=30` beside the
  real worker.
  - User 1 held 6 and user 2 held 4, leaving 0.
  - User 2 cancelled (DELETE 204), leaving 4.
  - User 1 walked away. At t=31 s, 10 seats were left; the worker log showed
    "released 1 expired hold(s)" at 18:51:29.269 for a hold expiring at
    18:51:29.
  - Everything was cleaned up afterwards.

**Small fixes:** mypy wanted explicit `str()` around values read from Redis
(redis-py's type hints allow bytes too).

**Key concepts:** idempotent operations, state machines (HELD -> RELEASED /
EXPIRED), sweepers and background workers, sorted sets as time indexes,
injecting time for testing, safety-net TTLs.

**Understanding check:** deferred to the end of the project.

---

## S2.8: A missing counter is rehydrated, never zero, test 12 (2026-11-08)

**What was built:**
- `app/redis/rehydrate.py`:
  - `seats_in_active_holds` scans `holds:expiry` for HELD/CONFIRMING holds
    on the tier.
  - `compute_available` = capacity - sold - held - pending (0 until Phase
    C), clamped at 0.
  - `rehydrate_tier` takes redis-py's `Lock` (10 s, non-blocking), re-checks
    under the lock, writes with SET NX and releases the lock. Requests that
    didn't get the lock poll for up to 2 s.
- `app/redis/keys.py`: `rehydrate_lock_key`.
- `app/services/holds.py`: on NOT_INITIALISED, rehydrate, then retry once;
  503 only if that fails.
- Tests:
  - New: `tests/adversarial/test_12_missing_counter_is_rehydrated.py` (5).
  - The old "missing counter gives 503" test now expects the rebuild.
  - The test 6 "503 isn't stored" case now makes a real 503 by holding the
    rebuild lock.

**Ran it:**
- 143/143 tests passed; test 12 passed 3 runs in a row; ruff and mypy are
  clean.
- 50 simultaneous requests on a missing counter: 1 rebuild, 25 x 201 (2
  seats each), the rest sold_out, and the counter ends at 0.
- Live break-it demo (capacity 10, holds of 4 + 3, counter deleted):
  - "Missing = 0" would wrongly sell out.
  - "Reset to capacity" would oversell (17 of 10).
  - The rebuild computed 3 (correct), and the next real hold triggered it
    automatically.

**Key concepts:** cache rebuild (rehydration), single-flight and the
thundering-herd problem on a cache miss, distributed locks with expiry,
SET NX, choosing the safe direction when counts may be stale (under-sell,
never over-sell).

**Understanding check:** deferred to the end of the project.

---

## S2.9: The real concurrency test (test 1), compared with S2.1 (2026-11-08)

**What was built:**
- `tests/concurrency/test_01_concurrent_holds_never_oversell.py`:
  - A start barrier and 500 HTTP buyers (1 to 4 seats each, seeded random)
    on 50 seats.
  - Parametrised: seeds 1 and 2 x counter present or missing.
  - Asserts: no oversell, seats balance, refusals are exactly `sold_out`, no
    wrongful refusals, hold records and uhold match, Postgres untouched.
- `learning/examples/s2_9/three_replicas_demo.py`:
  - 3 uvicorn processes, round-robin buyers, Redis and Postgres checks, and
    the S2.1 naive comparison.
  - A unique admin per run, cleanup in `finally`, and failures counted
    rather than aborting the run.

**Ran it:**
- Test 1: all 4 variants passed, 3 runs in a row. Full suite 147/147.
- **Mutation check:** with a naive check-then-take plugged in, test 1 failed:
  `assert 52 <= 50`.
- 3-process demo:
  - 100 buyers / 50 seats: 50 + 50.
  - 300 / 50: 50 + 250.
  - **1,000 / 100: exactly 100 x 201, 900 x 409, 0 oversold.** S2.1 naive
    right after: 103 sold (counter -3).

**Debugging moments:**
1. The first 1,000-buyer run timed out on the client (`httpx.PoolTimeout`),
   and its cleanup then couldn't reach Redis. The leftover demo admin broke
   the second run. Fixes: a unique admin per run, cleanup in `finally`,
   `return_exceptions=True`, a 60 s client timeout, and the demo now takes
   `--buyers` / `--seats`.
2. Measured why it was slow (all ms): Redis PING 1.8, Postgres SELECT 1 2.2,
   `/health/live` 8.8, `/health/ready` 22.8. Throughput was about 37 holds/s
   across 3 processes. Logged in `docs/design.md` for S8.3; no performance
   claims yet.

**Phase B ("Never oversell", M2) is now built.** The phase review is next.

**Key concepts:** start barriers, seeded randomness for reproducible tests,
invariant checks across stores, mutation testing (proving a test can fail),
replicas sharing state only through Redis and Postgres, measuring before
optimising.

**Understanding check:** deferred to the end of the project.

---

## Phase C starts. S3.1: Transactions primer; orders and tickets tables (2026-11-09)

**What was built:**
- `app/db/order_models.py` (a new file, keeping `models.py` under 200
  lines).
  - `OrderStatus` and `TicketStatus`.
  - `Order`: UUID id, user / event / tier FKs, quantity, `hold_id` UNIQUE,
    `idempotency_key`, status (default PENDING), total_cents, created_at.
    Plus `UNIQUE(user_id, idempotency_key)`, CHECKs and indexes.
  - `Ticket`: bigint id, order / event / tier FKs, `seat_id` (nullable, no FK
    until S6.1), `ticket_number` > 0, status (default ISSUED). Plus the two
    partial unique indexes and indexes.
- `app/db/__init__.py` imports both model modules, so every table is
  registered everywhere.
- Migration `e1f323bd4791` was reviewed, applied, `alembic check` came back
  clean, and downgrade -1 / upgrade worked.
- Tests: `tests/integration/test_order_tables.py` (10, on a real DB, naming
  the constraint that fires). The model test and conftest cleanup now
  include the new tables, with the cleanup list moved into an `ALL_TABLES`
  constant.
- `learning/07b-transactions.md` and
  `learning/examples/s3_1/transaction_demo.py`.

**Ran it:**
- 157/157 tests passed; ruff and mypy are clean.
- Transaction demo: as separate steps, a failed second write left a
  half-done order; in one transaction, both rolled back together. The
  database was unchanged afterwards.

**Schema decision:** `orders.tier_id` and `orders.quantity` were added
beyond the CLAUDE.md column list, because the spec's rehydrate formula and
purchase cap need them (recorded in `docs/design.md`).

**Comfort check for Phase C:** not asked (learning deferred).

**Key concepts:** transactions and ACID, commit and rollback, savepoints,
UUID primary keys, partial unique indexes, NULLs in unique indexes.

**Understanding check:** deferred to the end of the project.

---

## S3.2: The mock payment step (2026-11-09)

**What was built:**
- `app/services/payments.py`: `MockPaymentProvider` with test tokens
  (`tok_ok`, `tok_declined`, `tok_unavailable`), a configurable
  `failure_rate`, an injectable `random.Random`, idempotent `charge()` per
  key, and `refund()`.
- Errors: InvalidPaymentToken 422, PaymentDeclined 402, and
  PaymentUnavailable 503 with Retry-After.
- Setting `payment_failure_rate` (default 0.0), plus `.env.example`.
- `app/main.py` creates one provider at startup; `get_payments` dependency.
- `tests/unit/test_payments.py` (12): tokens, typed errors, idempotency,
  0%/100% rates, the seeded 30% rate (repeatable, 250-350 of 1,000),
  refunds, and "no payment route exists" (checked via the OpenAPI schema).

**Ran it:**
- 169/169 tests passed; ruff and mypy are clean.

**Design point:** section 9 forbids simulation endpoints, so the mock is a
server-side class that copies how real providers work (the client gets a
token, the server charges it), not a fake HTTP route.

**Small fix:** the test first read `app.routes`, but this FastAPI version
keeps included routers as `_IncludedRouter` objects. It now reads the
OpenAPI schema, the public list of routes.

**Key concepts:** payment tokens vs card numbers, charge then refund,
idempotent external calls, 402 Payment Required, seeded randomness, test
doubles (mocks).

**Understanding check:** deferred to the end of the project.

---

## S3.3: consume_hold.lua and POST /holds/{id}/confirm; tests 2 and 3 (2026-11-09)

**What was built:**
- `app/db/outbox_models.py`: an `outbox_events` table (migration
  `9851ce2da7c7`) with a partial index on `next_retry_at` for PENDING rows.
- `consume_hold.lua` (HELD -> CONFIRMING; owner/expiry checks; moves the
  hold to `holds:confirming`; returns event, tier and qty) and
  `revert_hold.lua` (CONFIRMING -> HELD). Wrappers are in
  `app/redis/confirm_scripts.py`.
- `app/services/orders.py`: `confirm_hold` (consume, price + cap pre-check,
  charge, then one transaction for the order + outbox with a user-row lock;
  revert and refund on any failure).
- New errors HoldExpired 410, ConfirmInProgress 409 and
  PurchaseLimitExceeded 409. New settings `purchase_user_cap` and
  `confirm_grace_seconds`.
- `app/api/idempotent.py`: `run_idempotently`, shared by holds and confirm
  (the hold route was refactored onto it).
- `app/api/orders.py`: `POST /holds/{hold_id}/confirm` returns 202
  `{order_id, status}`.
- Rehydrate counts holds in both indexes, plus PENDING orders whose hold is
  gone.
- Robustness: rehydrate and the sweeper skip malformed hold entries.
- Tests:
  - `tests/integration/test_confirm_api.py` (14).
  - Adversarial test 2 (2) and test 3 (6).
  - Test 12 +2, test 5 +1.
  - `tests/sales.py` gained `buyers`, `payments` and `confirm()`.
- The S2.9 demo cleanup now deletes only its own keys.

**Ran it:**
- 192/192 tests passed; ruff, mypy and `alembic check` are clean; the
  confirm race and retry tests passed 3 runs in a row.
- Live against the dev stack:
  - `tok_declined`: 402, and the hold was given back.
  - `quantity=100`: 422.
  - `tok_ok`: 202 PENDING.
  - Retry: the same order, replayed.
  - Postgres showed the order (2 seats, 9000 cents) and its `order.placed`
    outbox row PENDING.

**Debugging moments:**
1. A helper script failed to write `holds.py` (Errno 22), so the new import
   was never added. ruff then removed the old imports, which made 13 tests
   fail. The fix was adding the import directly, then re-checking.
2. **The safety classifier blocked a demo** whose cleanup would have
   TRUNCATEd whole tables and deleted every `hold:*` key on the dev stack.
   It was rewritten to delete only its own rows and keys. The committed S2.9
   demo had the same flaw and was fixed (a planted unrelated key survived
   the run).
3. That check exposed a real fragility: one malformed hold entry made every
   rebuild fail (500/503s) and would have stalled the sweeper. Both now skip
   it, with regression tests.
4. A shell heredoc for these docs failed to parse and wrote nothing. The docs
   were re-applied from files.

**Key concepts:** state machines across systems (Redis hold status plus DB
order status), compensating actions (revert, refund), one transaction for
data plus its outbox, row locks scoped per user, not trusting the client,
409 vs 410 vs 402.

**Understanding check:** deferred to the end of the project.

---

## S4.1: Outbox primer; a basic relay using SKIP LOCKED (2026-11-09)

**What was built:**
- `learning/14-outbox-pattern.md`, the primer, plus
  `learning/examples/s4_1/skip_locked_demo.py`.
- `app/worker/relay.py`:
  - `relay_batch` selects due PENDING rows, oldest first, 50 at a time,
    `FOR UPDATE SKIP LOCKED`. It XADDs each one to `stream:orders` in its own
    try/except, marks it PUBLISHED, then commits.
  - `run_relay` loops forever, going again straight away after a full batch.
- `ORDERS_STREAM_KEY = "stream:orders"` in `app/redis/keys.py`.
- `app/worker/main.py` now runs the sweeper and the relay side by side in an
  `asyncio.TaskGroup`.
- Each stream entry carries `outbox_id`, `type`, `aggregate_id` and
  `payload` (JSON text).
- Tests: `tests/integration/test_outbox_relay.py` (6), plus an end-to-end
  test in `test_confirm_api.py` (confirm, then relay, then a stream entry).
  `tests/sales.py` gained `stream_messages()`.

**Ran it:**
- 199/199 tests passed; ruff and mypy are clean.
- Mutation check:
  - plain `FOR UPDATE` (no SKIP LOCKED) fails the "locked row is skipped"
    test;
  - removing the lock entirely also fails "4 concurrent relays publish
    every row exactly once" (3 out of 3 runs).
- SKIP LOCKED demo on the dev DB: relay A locked rows [2, 3]; relay B's
  plain `FOR UPDATE` waited 1 s and gave up; `SKIP LOCKED` got [4] at once.
- The real worker on the dev stack: a demo outbox row was PUBLISHED and
  showed up in `stream:orders` within about a second. Only the demo's row
  and the (previously non-existent) stream were deleted afterwards.

**Debugging moments:**
1. asyncpg rejected the string `'0 seconds'` for an `interval` parameter (it
   wants a Python `timedelta`). Fixed by passing seconds to
   `make_interval(secs => :d)`.
2. redis-py's type hints say `xrange` might return `None`, so the tests read
   streams through a small typed helper.

**Key concepts:** the outbox pattern, at-least-once delivery (publish, then
mark), row locks that skip instead of wait, Redis Streams as an append-only
log, batch-and-loop background tasks.

**Understanding check:** deferred to the end of the project.

---

## S4.2: Relay retries, backoff and the DEAD state; test 8 (2026-11-09)

**What was built:**
- `app/core/job_errors.py`: `PermanentError`, for background jobs where a
  retry can't help.
- `app/worker/relay.py`:
  - `RetryPolicy` (8 attempts; 1 s, 2 s, 4 s ... capped at 300 s).
  - `record_failure` increments `attempts`, stores `last_error` and sets
    `next_retry_at` from the database clock. On a `PermanentError` or the
    last attempt, the row goes DEAD and an ERROR log is written as the alert.
  - An unknown event type raises `PermanentError` (there is no stream to
    send it to).
  - **Redis being unreachable counts no attempt:** the batch stops and the
    loop retries.
  - `delete_old_published` removes PUBLISHED rows older than 24 h, at most
    1,000 per call, once a minute.
- `tests/outbox.py` is a new shared pytest plugin (the `sessions` fixture and
  the row helpers).
- Tests:
  - adversarial test 8 (2 tests);
  - in `test_outbox_relay.py`, 4 new tests: backoff wait, Redis down costs
    no attempts, backoff maths, cleanup.

**Ran it:**
- 205/205 tests passed; ruff and mypy are clean.
- Mutation check, with four broken versions of the relay, each caught by at
  least one test:
  1. unknown types retried instead of DEAD;
  2. a Redis outage counted against rows;
  3. no backoff;
  4. a failing row stopping the batch.
- The real worker on the dev stack, with a poison row (type `demo.poison`)
  ahead of a good one: the poison row went DEAD after 1 attempt with
  `PermanentError: no stream for outbox event type 'demo.poison'`, and the
  good row was published right after it. Only the demo's two rows and the
  stream entry were deleted afterwards.

**Debugging moments:**
1. mypy treats `2 ** (n - 1)` as `Any` (a negative power gives a float), so
   the backoff uses `2.0 ** (n - 1)`.
2. The demo's id list picked up psql's "INSERT 0 2" footer, which broke the
   follow-up SELECT. The worker log had already shown the result; the rows
   were re-queried by id.

**Key concepts:** retryable vs permanent failures, exponential backoff, a
dead-letter state, not counting infrastructure outages against messages,
keeping a log table small.

**Understanding check:** deferred to the end of the project.

---

## S4.3: Redis Streams primer; XADD; a worker reading with a consumer group (2026-11-09)

**What was built:**
- `learning/15-redis-streams.md`, the primer, plus
  `learning/examples/s4_3/stream_demo.py` (two consumers, one entry left
  unacked).
- `app/worker/consumer.py`:
  - `StreamMessage` and `parse_message`; malformed fields raise
    `PermanentError`.
  - `ensure_group`: `XGROUP CREATE ... 0 MKSTREAM`. If another worker
    created the group first, it checks with `XINFO GROUPS` instead of
    matching the error text.
  - `consume_batch`: `XREADGROUP >`, then a handler per message type; XACK
    only after the handler succeeds; a failure stays pending and the rest of
    the batch continues.
  - `run_consumer`, the loop.
- **Deliberately not started by the worker yet:** it joins in S4.5 with the
  ticket handler, so it never runs with nothing real to do. The group starts
  at id 0, so nothing published in the meantime is missed.
- Tests: `tests/unit/test_stream_message.py` (5) and
  `tests/integration/test_stream_consumer.py` (7).

**Ran it:**
- 217/217 tests passed; ruff and mypy are clean.
- Mutation check, with three broken consumers, each caught:
  1. the group created at `$` (misses earlier messages);
  2. XACK before handling;
  3. one failure stopping the batch.
- The demo on the dev stack: worker-a got orders 1-2 and worker-b got 3-4;
  order-4 was never acked, so XPENDING showed 1 pending for worker-b, and
  `>` handed out nothing more.
- End to end on the dev stack: a demo outbox row went through the relay to
  the consumer group, the handler received the parsed message, it was
  acked, and 0 were pending. The script refused to run if `stream:orders`
  already existed, and it deleted only its own row and the stream it
  created.

**Debugging moments:**
1. redis-py types the `XREADGROUP` reply loosely (mypy saw `str | int`), so
   one typed helper (`read_new_entries`) converts it into plain
   `(entry_id, fields)` pairs.
2. A scratch script outside the project couldn't import `app` until it was
   run with `PYTHONPATH=.`.

**Key concepts:** append-only logs, consumer groups, the pending entries
list, ack-after-work (at-least-once), blocking reads, starting a group at 0
vs `$`.

**Understanding check:** deferred to the end of the project.

---

## S4.4: Idempotent processing; test 7 and the "process it twice" demo (2026-11-09)

**What was built:**
- The `processed_messages(message_id PK, processed_at)` table (model in
  `app/db/outbox_models.py`, migration `3eba02378c23`). `message_id` is
  the **outbox row id**, not the stream entry id, because a relay
  duplicate gets a new entry id but keeps its outbox id.
- `app/worker/idempotency.py`:
  - `claim_message` does `INSERT ... ON CONFLICT DO NOTHING RETURNING`;
    False means a duplicate.
  - `run_once(session_factory, handler)` opens one transaction, claims the
    message, then runs the handler with the same session. A duplicate
    returns normally, so it gets acked.
- Adversarial test 7 (3 tests). Ticket issuing is S4.5, so the test handler
  adds the order's quantity to `tiers.sold`, the counter S4.5 builds on.
  S4.5 extends test 7 to real tickets.
- `learning/examples/s4_4/process_twice_demo.py`.
- `tests/unit/test_models.py` (the table list), `ALL_TABLES` and the outbox
  test plugin's cleanup now include `processed_messages`.

**Ran it:**
- 220/220 tests passed; ruff, mypy and `alembic check` are clean; the
  migration was applied to the dev DB.
- Mutation check, with three broken versions, each caught:
  1. no claim;
  2. the claim committed in its own transaction before the work (a crash
     after the claim would silently lose the order);
  3. keyed by the stream entry id instead of the outbox id.
- The demo on the dev stack: one 2-seat order delivered twice gave
  **sold = 4 without idempotency and sold = 2 with `run_once`**. It deleted
  only its own user, event, tier, processed mark (a negative id, which can
  never be a real outbox id) and stream.

**Debugging moments:**
1. The full suite caught that `test_all_tables_are_registered` lists every
   table: a guard test doing its job when a new table appears. The new
   table was added to the list.

**Key concepts:** idempotency for consumers, recording "done" in the same
transaction as the work, `ON CONFLICT DO NOTHING`, how a unique key makes
concurrent duplicates wait for each other, choosing the right
de-duplication key.

**Understanding check:** deferred to the end of the project.
