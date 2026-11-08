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
