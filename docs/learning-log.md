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
