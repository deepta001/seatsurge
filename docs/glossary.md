# Glossary

Plain-English meanings of every technical term, with where it first appears.

## Setup and tools (S0.1)

| Term | Meaning | Where it appears |
|---|---|---|
| PATH | The list of folders Windows searches when you type a command name. A program can be installed but still "not found" if its folder isn't listed. Terminals read PATH when they open, so restart them after installing. | Your Windows settings, S0.1 |
| winget | Windows' built-in app installer that you drive by typing commands. | S0.1 installs |
| Per-user install | A program installed only for your Windows account (under `AppData`), usually without admin rights. | Python, uv |
| System-wide install | A program installed for every account (under `Program Files`); needs administrator rights. | Git |
| Exit code | The number a program returns when it finishes: 0 means success, anything else means something went wrong (or "not found"). | Every command |
| Git | A tool that saves snapshots ("commits") of your code, so you can see what changed and go back. | The whole project |
| uv | A tool that installs a project's Python libraries into that project's own private folder, so projects don't interfere with each other. | `pyproject.toml` (from S0.4) |
| Docker image | A recipe or template for a container: the program plus everything it needs. | `docker-compose.yml` (from S0.7) |
| Docker container | A sealed, running box made from an image. It can be deleted and recreated in seconds. | Postgres and Redis (from S0.7) |
| Docker daemon | The background service that actually builds and runs containers. | Docker Desktop |
| Docker client | The `docker` command you type; it sends instructions to the daemon. | Your terminal |
| Docker Hub | An online library of ready-made images (for example `postgres`, `redis`). | `docker-compose.yml` |

## Big picture (S0.2)

| Term | Meaning | Where it appears |
|---|---|---|
| API | The part of the server that receives requests ("hold a seat", "confirm") and sends back answers. | `app/api/` |
| Request / response | A message the client sends to the server, and the server's reply. | Every endpoint |
| Replica | One of several identical copies of the API running at the same time, so more users can be served. | `docker-compose.yml` (3 replicas) |
| Load balancer (nginx) | A traffic director that spreads incoming requests across the replicas. | `deploy/nginx.conf` |
| Redis | A very fast in-memory data store. Our "fast gate" for seat counts and holds. | `app/redis/` |
| PostgreSQL (Postgres) | A database that stores data safely on disk. Our "source of truth". | `app/db/` |
| Hold | A seat with a "reserved for 5 minutes" sticker. It expires if you don't confirm. | `app/services/holds.py` |
| Order | A confirmed purchase, written in the database. | `orders` table |
| Outbox | A to-do note written into the database in the same step as the order, so the follow-up work can't be lost. | `outbox_events` table |
| Worker | A background process that picks up the to-do notes and issues the actual tickets. | `app/worker/` |
| Concurrency | Many things happening at the same time (many users clicking "buy" together). | The whole project |
| Race condition | A bug where the result depends on who gets there first, such as two people both "seeing" the last seat. | S2.1 demo |
| Check-then-act | The naive pattern "look at the count, then change it". It breaks when someone else changes the count in between. | S2.1 demo |
| Atomic | Happens as one indivisible step: all or nothing, with nobody able to sneak in halfway. | Lua scripts (S2.3) |
| Overselling | Selling more tickets than there are seats. The one thing this project must never do. | Every test |
| Thundering herd | A huge crowd hitting the system at the same instant (for example when tickets go on sale). | Load test (S8.3) |

## Python basics (S0.3)

| Term | Meaning | Where it appears |
|---|---|---|
| Type hint | A label saying what type a value should be (`quantity: int`, `-> bool`). Python doesn't enforce it when running; editors and mypy check it. | `learning/examples/s0_3/seats.py` |
| mypy | A tool that reads your code and reports type-hint mismatches before you run it. | CI (from S0.9) |
| Class | A template for objects that bundle data with the actions on that data. | `Tier` in `seats.py` |
| Method | A function that belongs to a class, such as `Tier.sell`. | `seats.py` |
| `self` | Inside a method, "this particular object". | `seats.py` |
| Module | Any `.py` file. Other files can import things from it. | `seats.py` |
| Import | Loading a module so you can use its classes or functions (`from seats import Tier`). | `main.py` |
| `if __name__ == "__main__":` | Code under this only runs when the file is started directly, not when it's imported. | `main.py` |
| Traceback | Python's error report: the chain of calls that led to the error, with the actual error on the last line. | The S0.3 break-it demo |
| Early return | Leaving a function as soon as you know the answer, which keeps the code flat and readable. | `Tier.sell` |
| Virtual environment (venv) | A private copy of Python with its own installed libraries, kept in a folder (usually `.venv`). | `learning/examples/.venv-demo`, the project's `.venv` (S0.4) |
| `sys.prefix` | Where the running Python lives. It changes when you're inside a venv. | The S0.3 venv demo |

## Web basics (S0.5)

| Term | Meaning | Where it appears |
|---|---|---|
| HTTP | The language browsers and apps use to talk to servers: a request goes in and a response comes back. | Every endpoint |
| HTTP method | The kind of action: `GET` reads, `POST` creates, `PATCH` changes, `DELETE` removes. | `@app.get` in `app/main.py` |
| Path | The part of the URL that names the thing, such as `/events/42`. | Routes |
| Status code | A number in the response saying how it went: 200 OK, 201 Created, 404 Not Found, 409 Conflict, 500 server error. | `learning/02-http-basics.md` |
| JSON | Text-format data that looks like Python dicts and lists; the usual request and response body. | `{"message": ...}` |
| REST | A convention: paths name things (nouns) and methods say the action. | The API surface |
| Route / endpoint | One method plus path that the server answers, such as `GET /`. | `read_root` in `app/main.py` |
| FastAPI | The Python web framework: you write functions, and it turns HTTP requests into calls to them. | `app/main.py` |
| uvicorn | The server program that listens on a port and hands requests to FastAPI. | `python -m uvicorn app.main:app` |
| Port | A numbered "door" on a computer that a server listens on (8000 here). | `--port 8000` |
| `async def` | A function that can pause while it waits (for a database, say), letting the server handle other requests meanwhile. | `read_root` |
| OpenAPI / Swagger UI | A machine-readable description of the API (`/openapi.json`) and the interactive page built from it (`/docs`). | http://127.0.0.1:8000/docs |
| Dependency (library) | Someone else's code our project uses, listed in `pyproject.toml` and pinned in `uv.lock`. | `pyproject.toml` |
| Smart App Control | A Windows 11 security feature that blocks unsigned programs. It blocks the `.exe` launchers inside `.venv`, so run tools as `python -m <tool>`. | S0.5 |

## Settings (S0.6)

| Term | Meaning | Where it appears |
|---|---|---|
| Environment variable | A name=value pair the operating system gives to a program when it starts. | `$env:ENVIRONMENT` |
| `.env` file | A local, never-committed file of name=value lines holding your real settings and secrets. | Project root (gitignored) |
| `.env.example` | The committed template for `.env`, with `CHANGE_ME` placeholders. | `.env.example` |
| Settings | The app's configuration: database address, passwords, environment name. | `app/core/settings.py` |
| pydantic-settings | A library that fills a typed class from environment variables and `.env`, validating each value. | `Settings` |
| Validation | Checking that a value has the right type and form, and rejecting it with a clear error if not. | The `ValidationError` in the S0.6 demo |
| Fail fast | Crashing immediately at startup with a clear message, rather than failing later in confusing ways. | Required `database_url` |
| `SecretStr` | A type that hides its value when printed (`**********`), so secrets don't end up in logs. | `database_url`, `redis_url` |
| `Literal` | A type hint that allows only specific values, such as `"local"`, `"test"` or `"production"`. | `Settings.environment` |
| `@lru_cache` | A decorator that remembers a function's result, so later calls reuse it instead of redoing the work. | `get_settings()` |
| Connection URL | A one-line address for a service: `driver://user:password@host:port/name`. | `DATABASE_URL`, `REDIS_URL` |

## Infrastructure and connections (S0.7)

| Term | Meaning | Where it appears |
|---|---|---|
| Docker Compose | A tool that starts several containers together from one file (`docker compose up`). | `docker-compose.yml` |
| Service (Compose) | One named container definition in the Compose file, such as `postgres` or `redis`. | `docker-compose.yml` |
| Volume | Storage that outlives the container, so data survives `docker compose down`. | `postgres-data` |
| Port mapping | Connecting a port on your computer to a port inside a container (`127.0.0.1:5432:5432`). | `docker-compose.yml` |
| Healthcheck | A command Docker runs repeatedly to see whether a service is ready. | `pg_isready`, `redis-cli ping` |
| Alpine image | A very small Linux base used to make images lighter (`postgres:16-alpine`). | `docker-compose.yml` |
| SQLAlchemy | The Python library we use to talk to Postgres, through SQL text or Python classes. | `app/db/session.py` |
| asyncpg | The fast async Postgres driver underneath SQLAlchemy (the `+asyncpg` in the URL). | `DATABASE_URL` |
| Engine | SQLAlchemy's object that owns the connection pool to the database. | `create_db_engine()` |
| Connection pool | A set of open connections that are reused, because opening a new one per request is slow. | `create_db_engine()`, the Redis client |
| `pool_pre_ping` | Checks that a pooled connection still works before using it. | `app/db/session.py` |
| redis-py (`redis.asyncio`) | The Python client library for Redis. | `app/redis/client.py` |
| TTL (time to live) | How long a Redis key lives before Redis deletes it automatically (`ex=10` means 10 seconds). | `check:hello` in the check script |
| `asyncio.run` | Starts the event loop and runs one async function to completion. | `scripts/check_connections.py` |
| `AuthenticationError` / `ConnectionError` | Redis errors for a wrong password and for "nobody is listening on that port". | The S0.7 break-it demo |

## Health checks and testing (S0.8)

| Term | Meaning | Where it appears |
|---|---|---|
| Liveness check | "Is the process running?" It touches nothing else; if it fails, restart the process. | `GET /health/live` |
| Readiness check | "Can it do real work right now?" It checks Postgres and Redis; if it fails, stop sending traffic, but don't restart. | `GET /health/ready` |
| 503 Service Unavailable | The status code for "temporarily can't serve; try another replica or later". | `/health/ready` when a check fails |
| Lifespan | Code that runs once at app startup (before `yield`) and shutdown (after it). | `lifespan()` in `app/main.py` |
| `app.state` | A place on the app object to keep shared things, such as the engine and Redis client. | `app/main.py` |
| Dependency (FastAPI) | A function named in `Depends(...)` whose result FastAPI passes into a route. Tests can override it. | `app/api/dependencies.py` |
| Router | A group of related routes, added to the app with `include_router`. | `app/api/health.py` |
| Response model | A pydantic class describing exactly what a response contains; nothing extra leaks out. | `LiveResponse`, `ReadyResponse` |
| `asyncio.timeout` | Cancels the code inside it if it takes too long, raising `TimeoutError`. | `postgres_is_up`, `redis_is_up` |
| `asyncio.gather` | Runs several async calls at the same time and waits for all of them. | `ready()` |
| pytest | The test runner: finds `test_*` functions and reports which `assert`s fail. | `tests/` |
| Fixture | Reusable test setup that pytest passes in by parameter name. | `client` in `test_health.py` |
| `conftest.py` | A pytest file loaded automatically before tests; shared setup goes here. | `tests/conftest.py` |
| monkeypatch | A pytest fixture that temporarily replaces something for one test. | Faking Redis down |
| TestClient | Sends fake HTTP requests into the app without a real server (needs httpx). | `test_health.py` |
| Dev dependency | A library needed only for development or testing, never shipped with the app. | `[dependency-groups] dev` in `pyproject.toml` |
| IPv6 / `::1` | The newer internet address format; `::1` is IPv6's "this computer", like 127.0.0.1 in IPv4. | The S0.8 localhost bug |

## Code quality and CI (S0.9)

| Term | Meaning | Where it appears |
|---|---|---|
| Linter | A tool that reads code and flags mistakes and risky patterns without running it. | ruff |
| Formatter | A tool that rewrites code into one consistent layout, so style is never argued about. | `ruff format` |
| ruff | Our linter and formatter, configured in `[tool.ruff]`. | `pyproject.toml` |
| Static type checker | A tool that checks type hints across the code before it runs (it caught `capacity='3'`). | mypy |
| mypy strict mode | The strictest mypy settings: no `Any` leaks, every type is explicit. Used on `app/services`. | `[[tool.mypy.overrides]]` |
| CI (continuous integration) | Automatically running the checks on a clean machine for every push, so broken code is noticed at once. | `.github/workflows/ci.yml` |
| GitHub Actions | GitHub's CI service; it runs the workflow files in `.github/workflows/`. | `ci.yml` |
| Workflow / job / step | A workflow is a CI file; a job is one machine running it; steps are the commands it runs in order. | `ci.yml` |
| `uv sync --locked` | Installs exactly what's in `uv.lock`, and fails if the lockfile is out of date. | The CI install step |

## Database models (S1.1)

| Term | Meaning | Where it appears |
|---|---|---|
| Table / row / column | A named grid of data; one record in it; one typed field. | `users`, `events`, `tiers` |
| Primary key | The column that uniquely identifies each row (`id`). | `pk_users`, `pk_events`, `pk_tiers` |
| SERIAL | A Postgres integer column whose value comes from an automatic counter (sequence). | Every `id` |
| Foreign key | A column that must point at an existing row in another table. | `tiers.event_id`, `events.created_by` |
| NOT NULL | The column must have a value. | Any `Mapped[int]` or `Mapped[str]` |
| UNIQUE constraint | No two rows may share this value or combination. | `uq_users_email`, `uq_tiers_event_id_name` |
| CHECK constraint | A true/false rule every row must satisfy. | `ck_tiers_sold_within_capacity` |
| Constraint naming convention | A rule that gives every constraint a predictable name. | `NAMING_CONVENTION` in `app/db/base.py` |
| Server default | A default value applied by the database itself, even to rows inserted outside the app. | `role DEFAULT 'USER'` |
| Model (ORM) | A Python class that describes a table; SQLAlchemy turns it into SQL. | `User`, `Event`, `Tier` |
| ORM | Object-relational mapper: works with rows as Python objects instead of raw SQL. | SQLAlchemy |
| `DeclarativeBase` / metadata | The base class all models share; `metadata` is the list of every table. | `Base` in `app/db/base.py` |
| `Mapped[...]` / `mapped_column` | SQLAlchemy 2.0's typed way to declare a column and its options. | `app/db/models.py` |
| `StrEnum` | A Python enum whose members are also strings (`UserRole.USER == "USER"`). | `UserRole`, `SeatingType`, `EventStatus` |
| Schema (Postgres) | A namespace inside a database that holds tables (default: `public`). | `demo_s1_1` in the S1.1 demo |
| Rollback | Undoing every change in a transaction. | The end of the S1.1 demo |
| Savepoint | A checkpoint inside a transaction that you can roll back to without losing everything. | `begin_nested()` in the demo |
| Integer cents | Storing money as a whole number of cents, because floats can't represent 0.10 exactly. | `price_cents` |
| `TIMESTAMP WITH TIME ZONE` | A date-time that is an exact moment, unaffected by the server's time zone. | `starts_at`, `created_at` |

## Migrations (S1.2)

| Term | Meaning | Where it appears |
|---|---|---|
| Migration | A versioned script that changes the database schema one step, with an upgrade and a downgrade. | `migrations/versions/` |
| Alembic | The migration tool for SQLAlchemy. | `alembic.ini`, `migrations/env.py` |
| Revision / revision id | One migration, identified by a random id such as `19624396e697`. | Migration file names |
| `down_revision` | The revision before this one; together they form a chain. | Each migration file |
| head | The newest revision in the chain. | `alembic upgrade head` |
| base | "No migrations applied" (an empty schema). | `alembic downgrade base` |
| `alembic_version` | A one-row table where Alembic records which revision the database is on. | Postgres |
| Autogenerate | Alembic drafting a migration by diffing the models against the real database; always review it. | `alembic revision --autogenerate` |
| `alembic check` | Fails if the models contain changes no migration covers ("drift"). | The CI step "Migrations match the models" |
| Schema drift | When the code's models and the real database disagree. | The S1.2 break-it demo |
| Post-write hook | A command Alembic runs on every new migration file (ruff here). | `[post_write_hooks]` in `alembic.ini` |
| Service container (CI) | An extra container GitHub Actions runs beside the job, such as a throwaway Postgres. | `services:` in `ci.yml` |

## Registration (S1.3)

| Term | Meaning | Where it appears |
|---|---|---|
| Hash (password) | A one-way scramble: it can check a password but can't be reversed into one. | `app/core/security.py` |
| argon2 | A deliberately slow, memory-hungry password-hashing algorithm (the `argon2id` variant). | `hash_password()` |
| Salt | Random data mixed into each hash, so equal passwords get different hashes. | Stored inside the hash string |
| Domain error | A typed exception for an expected business failure, such as "user already exists". | `app/core/errors.py` |
| Exception handler | Code that turns a raised exception into an HTTP response. | `app/api/errors.py` |
| 409 Conflict | "This clashes with something that already exists." | Duplicate email or username |
| 422 Unprocessable Entity | "The request is badly formed": wrong fields, too short, unknown keys. | Bad sign-up data |
| `extra="forbid"` | A pydantic setting that rejects unknown fields instead of ignoring them. | `RegisterRequest` |
| Session (SQLAlchemy) | One unit of work with the database; changes are saved together by `commit()`. | `get_db_session()` |
| Session factory | Makes a fresh session per request. | `create_session_factory()` |
| `IntegrityError` | SQLAlchemy's error when a database constraint rejects a write. | `register_user()` |
| Check-then-insert race | Checking "is this free?" and then inserting, while someone else inserts in between. Avoided by letting a UNIQUE constraint decide. | `register_user()` |
| Integration test | A test that uses real services (a real Postgres) rather than stand-ins. | `tests/integration/` |
| Adversarial test | A test that plays the attacker or the failure, proving a protection holds. | `tests/adversarial/` |
| testcontainers | A library that starts throwaway Docker containers (here Postgres) for tests. | `postgres_url` fixture |
| pytest-asyncio | A pytest plugin that runs `async def` tests and fixtures. | `asyncio_mode = "auto"` |
| `ASGITransport` | An httpx transport that calls the FastAPI app directly, with no server or port. | The `client` fixture |
| `dependency_overrides` | FastAPI's way to swap a dependency in tests (here: the test database's session). | The `client` fixture |
| Start barrier | Making many tasks wait on one `asyncio.Event`, then releasing them together. | The 10-signups race test |
| TRUNCATE ... RESTART IDENTITY | Empties tables fast and resets their id counters. | After each integration test |

## Login and tokens (S1.4)

| Term | Meaning | Where it appears |
|---|---|---|
| JWT (JSON Web Token) | A signed token, `header.payload.signature`; the payload is readable, the signature makes it tamper-proof. | `app/core/tokens.py` |
| Access token | A short-lived JWT (15 min) proving who the caller is. | `POST /auth/login` |
| Claim | One fact inside a JWT payload, such as `sub`, `role`, `exp`. | `create_access_token()` |
| `sub` / `iat` / `exp` | Subject (the user id), issued-at time, expiry time. | Token payload |
| HS256 | HMAC with SHA-256: signing with one shared secret key. | `ALGORITHM` |
| Signing key / `JWT_SECRET_KEY` | The secret used to sign and check tokens; whoever has it can mint any token. | `.env`, settings |
| Algorithm pinning | Accepting only the algorithm we chose, so `alg: none` or swaps are refused. | `algorithms=[ALGORITHM]` |
| Bearer token | A token sent as `Authorization: Bearer <token>`; whoever holds it can use it. | `HTTPBearer` |
| 401 Unauthorized | "We don't know who you are": missing, wrong or expired credentials. | Login failure, `/me` without a token |
| `WWW-Authenticate` | A response header telling the client which kind of credentials to send. | `NotAuthenticated` |
| Stateless authentication | Trusting a signed token instead of looking the user up on each request. | `get_current_user()` |
| User enumeration | Discovering which accounts exist from differences in an app's answers. | Login's identical 401 |
| Timing side channel | Leaking information through how long something takes. | The dummy-hash check in `authenticate_user()` |
| `@dataclass(frozen=True)` | A small read-only class for holding values. | `AccessTokenClaims` |

## Refresh tokens (S1.5)

| Term | Meaning | Where it appears |
|---|---|---|
| Refresh token | A long-lived (7-day), single-use token whose only job is to get a new access token. | `POST /auth/refresh` |
| Token rotation | Every use of a refresh token replaces it with a new one. | `rotate_refresh_token()` |
| Token family | All refresh tokens descended from one login, sharing a `family_id`. | `refresh_tokens.family_id` |
| Reuse detection | Treating a second use of an already-used token as theft and revoking its family. | `_revoke_family_if_reused()` |
| Revocation | Making a token stop working before it expires. | `revoked_at`, `POST /auth/logout` |
| SHA-256 | A fast one-way hash; fine for long random tokens, too fast for passwords. | `hash_refresh_token()` |
| Entropy | How unpredictable a value is; 256 random bits can't be guessed. | `secrets.token_urlsafe(32)` |
| `UPDATE ... RETURNING` | Change rows and get back values from exactly the rows that changed, in one statement. | Claiming a refresh token |
| Conditional update | An UPDATE whose WHERE clause makes it apply only if the row is still in the expected state. | `WHERE used_at IS NULL ...` |
| `ON DELETE CASCADE` | Deleting a parent row also deletes the rows that point at it. | `refresh_tokens.user_id` |
| UUID | A 128-bit random identifier, unique without a central counter. | `family_id` |
| 204 No Content | "Done; there's nothing to send back." | `POST /auth/logout` |

## Admin event management (S1.6)

| Term | Meaning | Where it appears |
|---|---|---|
| Authentication vs authorisation | Authentication: *who are you?* (401 if unknown). Authorisation: *are you allowed?* (403 if not). | `get_current_user` vs `require_admin` |
| 403 Forbidden | "We know who you are, but you may not do this." | A USER calling an admin route |
| 404 Not Found | "There's nothing with that id." | `EventNotFound` |
| CRUD | Create, Read, Update, Delete: the basic operations on a resource. | `/events` routes |
| PATCH | An HTTP method for a partial update: send only the fields to change. | `PATCH /events/{id}` |
| State machine | A fixed set of statuses and the allowed moves between them. | `ALLOWED_STATUS_CHANGES` |
| `flush` vs `commit` | `flush` sends pending SQL inside the transaction (so ids exist); `commit` makes it permanent. | `create_event()` |
| `SELECT ... FOR UPDATE` | Locks the selected rows until the transaction ends, so concurrent changes take turns. | `_get_locked()` |
| CLI | Command-line interface: a program you run in a terminal with arguments. | `scripts/seed_admin.py` |
| argparse | Python's standard library for reading command-line arguments. | `seed_admin.main()` |
| getpass | Reads a password from the terminal without showing it. | `seed_admin.read_password()` |
| `AwareDatetime` | A pydantic type that requires a time zone on date-times. | `EventCreate.starts_at` |
| Validator | A function pydantic runs to check a field or the whole model. | `tier_names_are_unique`, `something_to_change` |
| Parametrised test | One test function run several times with different inputs. | `test_bad_event_data_gets_422_and_nothing_is_saved` |

## Browsing events (S1.7)

| Term | Meaning | Where it appears |
|---|---|---|
| Pagination | Returning a long list in pages instead of all at once. | `GET /events` |
| `limit` / `offset` | Page size, and how many rows to skip before the page starts. | Query parameters of `GET /events` |
| Stable ordering | Sorting with a unique tie-breaker (`id`), so the same query always gives the same order. | `order_by(Event.starts_at, Event.id)` |
| Keyset pagination | Paging by "items after this one" instead of an offset; faster for deep pages. | `docs/design.md` (not used yet) |
| Query parameter | A `?name=value` part of a URL. | `?city=leeds&limit=10` |
| `ILIKE` | Postgres's case-insensitive pattern match. | Name search |
| LIKE wildcards | `%` = any characters, `_` = any one character. | `contains_pattern()` |
| Escaping | Marking special characters so they're treated literally. | `LIKE_ESCAPE` |
| `func.lower` | SQL's `lower()`, used for case-insensitive comparison. | City filter |
| `select(func.count())` | Counts matching rows in SQL instead of loading them. | `EventPage.total` |
| Public vs internal model | Different response shapes for different audiences, so internal fields never leak. | `EventDetail` vs `EventResponse` |

## Race conditions (S2.1)

| Term | Meaning | Where it appears |
|---|---|---|
| Stale read | Acting on a value that someone else has changed since you read it. | The check in the S2.1 demo |
| Intermittent bug | A bug that only appears sometimes, depending on timing; easy to miss in testing. | Redis oversold in 11 of 13 runs |
| `DECR` | A Redis command that subtracts 1 from a number atomically and returns the new value. | The S2.1 demo, Lua scripts later |
| Connection pool limit | The maximum number of open connections a client keeps; extra requests must wait, or fail. | `MaxConnectionsError` in S2.1 |
| `BlockingConnectionPool` | A redis-py pool that makes requests wait for a free connection instead of raising. | `demo_redis_client()` |
| Lock (`asyncio.Lock`) | Lets only one task at a time run a section; only works inside one process. | Primer 11 |

## Redis and Lua (S2.2)

| Term | Meaning | Where it appears |
|---|---|---|
| `redis-cli` | Redis's command-line client. | `docker compose exec redis redis-cli ...` |
| `INCR` / `DECRBY` | Atomically add 1, or subtract N, from a number stored in a key. | Inventory counters |
| `nil` | Redis's "no value": what `GET` returns for a missing key. Not the same as 0. | Rule 4, "missing is not zero" |
| `EXPIRE` / `EX` / `TTL` | Give a key a lifetime in seconds / set it while writing / see the seconds left (-2 = gone). | Holds expire |
| Hash (`HSET`, `HGETALL`) | A key holding named fields, like a small record. | `hold:{id}` |
| Sorted set (`ZADD`, `ZRANGEBYSCORE`) | Unique members, each with a score, kept in score order. | `holds:expiry` |
| Set (`SADD`, `SISMEMBER`) | Unique members with a fast "is X in it?" check. | `sold:{event}` |
| Lua | A small scripting language that Redis can run internally. | `take_seats.lua` |
| Lua script (Redis) | A script Redis runs as one atomic step; no other command runs mid-script. | `take_seats.lua`, `reserve_tier.lua` (S2.3) |
| `KEYS` / `ARGV` | The keys a script touches, and its other arguments (1-indexed, strings). | Lua scripts |
| `EVAL` / `EVALSHA` / `SCRIPT LOAD` | Run a script by its text / by its SHA fingerprint / load it to get that SHA. | S2.2 demo |
| `register_script` | redis-py helper that loads a script and calls it by SHA. | `run_with_lua()` |
| Return code | A number the script returns to say what happened (1 taken, 0 not enough, -2 missing). | `take_seats.lua` |

## Reserving seats in Redis (S2.3)

| Term | Meaning | Where it appears |
|---|---|---|
| `reserve_tier.lua` | The script that atomically checks and reserves general-admission seats and writes the hold. | `app/redis/lua/` |
| Per-user cap | The most seats one user may hold for one event at a time. | `uhold:{event}:{user}`, return code -3 |
| `ReserveOutcome` | The enum the Python wrapper turns the script's return codes into. | `app/redis/scripts.py` |
| Validate-then-write | Do every check before the first change, so a refusal changes nothing. | `reserve_tier.lua` |
| Key schema | The agreed names and types of all Redis keys. | `app/redis/keys.py` |
| `MULTI` / `EXEC` | A Redis transaction: queues commands and runs them together, but can't branch on values read inside it. | Why we use Lua instead (`docs/design.md`) |
| Snapshot assertion | Capturing state before an action and asserting it's identical after. | `snapshot()` in `test_reserve_tier.py` |
| `Redis.from_pool` | Builds a client that owns its pool, so closing the client closes the pool. | `build_redis_client()` |

## Holds over HTTP (S2.4)

| Term | Meaning | Where it appears |
|---|---|---|
| Hold | Seats reserved for one user for a few minutes, waiting to be confirmed. | `POST /events/{id}/holds` |
| `hold_id` | A random UUID naming one hold; the client sends it back to confirm (Phase C). | Hold response |
| 503 Service Unavailable + `Retry-After` | "Not ready right now; try again in N seconds." | `InventoryNotReady` |
| Sellability vs availability | Whether an event *may* be sold (DB facts) vs whether seats are *left* (Redis counter). | `create_hold()` |
| Thundering herd | Many clients hitting the same resource at the same moment, e.g. a sale opening. | The 300-buyer HTTP test |

## Idempotency (S2.5)

| Term | Meaning | Where it appears |
|---|---|---|
| Idempotent | Doing it twice has the same effect as doing it once. | Retried holds |
| `Idempotency-Key` | A client-made unique id for one attempt, resent unchanged on every retry. | Header on `POST /events/{id}/holds` |
| Request fingerprint | A hash of what was asked, used to spot a key reused for something different. | `request_fingerprint()` |
| `SET ... NX` | "Set only if the key doesn't exist": an atomic claim that exactly one caller wins. | `idempotency.begin()` |
| Replay | Returning the stored answer instead of doing the work again. | `Idempotent-Replayed: true` |
| Crash window | The gap between two steps where a crash leaves things half-done. | `docs/design.md`, S2.5 |
| `pytest_plugins` | Loads a module of fixtures for every test. | `tests/conftest.py` -> `tests/sales.py` |

## Request limits (S2.6)

| Term | Meaning | Where it appears |
|---|---|---|
| Middleware | Code that wraps every request before (and after) it reaches the routes. | `BodySizeLimitMiddleware` |
| ASGI | The standard interface between async Python web servers (uvicorn) and apps (FastAPI): `scope`, `receive`, `send`. | `app/api/body_limit.py` |
| `Content-Length` | A header saying how many bytes the body has; clients can lie or leave it out. | The middleware's first check |
| Chunked transfer | Sending a body in pieces without declaring its total size up front. | `test_a_chunked_body_with_no_length_...` |
| 413 Payload Too Large | "Your request body is bigger than I accept." | `payload_too_large` |
| Denial of service (DoS) | Making a service unusable by overloading it, e.g. with huge requests. | Why bodies are capped |
| Defence in depth | Several independent protections, so one gap doesn't break everything. | Field limits + body cap + Redis cap |

## Releasing holds (S2.7)

| Term | Meaning | Where it appears |
|---|---|---|
| Release | Giving a hold's seats back to the inventory. | `release_hold.lua` |
| Hold status | HELD -> RELEASED (user cancelled) or EXPIRED (time ran out); later CONFIRMING -> CONSUMED. | The `status` field of `hold:{id}` |
| Sweeper | A background job that finds expired holds and releases them. | `app/worker/sweeper.py` |
| Worker process | The second process type, beside the API, running background jobs. | `python -m app.worker.main` |
| `ZRANGEBYSCORE ... LIMIT` | Fetch sorted-set members with scores in a range, a batch at a time. | `sweep_expired_holds()` |
| `ZREM` | Remove a member from a sorted set. | Releasing a hold |
| Safety-net TTL | An expiry that cleans up if normal cleanup ever fails. | `uhold` EXPIRE |
| Time injection | Passing "now" into code, so tests can jump ahead instead of waiting. | `sweep_expired_holds(now=...)` |

## Rehydration (S2.8)

| Term | Meaning | Where it appears |
|---|---|---|
| Rehydrate | Rebuild a missing cached value (the Redis counter) from the source of truth (Postgres + active holds). | `app/redis/rehydrate.py` |
| Cache miss | Looking for a cached value that isn't there. | NOT_INITIALISED from `reserve_tier.lua` |
| Cache stampede | Many requests all rebuilding the same missing value at once. | Prevented by the rebuild lock |
| Single-flight | Only one caller does an expensive job; the others wait for its result. | `rehydrate_tier()` |
| Distributed lock | A lock shared across processes and machines, here a Redis key with an expiry. | `lock:rehydrate:{event}:{tier}` |
| Lock timeout | A lock frees itself after a while, so a crashed holder can't block everyone forever. | `LOCK_SECONDS = 10` |
| Safe direction | When a count might be stale, err towards selling too few, never too many. | The `max(0, ...)` clamp; release races |

## Proving it (S2.9)

| Term | Meaning | Where it appears |
|---|---|---|
| Invariant | Something that must always be true, e.g. "seats held + seats left = capacity". | Test 1's assertions |
| Seeded randomness | Random choices from a fixed seed, so a failing run can be replayed exactly. | `random.Random(seed)` in test 1 |
| Mutation testing | Deliberately breaking the code to prove a test notices. | The naive-reserve plugin (52 of 50) |
| Replica | One of several identical copies of the API process. | `three_replicas_demo.py` |
| Round-robin | Sending requests to replicas in turn: 1, 2, 3, 1, 2, 3... | The demo; nginx in S8.1 |
| Wall time | Real elapsed time, as a clock on the wall would show. | Demo output |
| Throughput | How many requests are completed per second. | The S2.9 performance finding |
| Latency | How long one request takes. | `latency_probe` measurements |

## Orders and transactions (S3.1)

| Term | Meaning | Where it appears |
|---|---|---|
| Transaction | A group of database changes that all happen, or none do. | `engine.begin()`, `session.commit()` |
| ACID | Atomic, Consistent, Isolated, Durable: the four promises of a transaction. | `learning/07b-transactions.md` |
| Commit / rollback | Make a transaction's changes permanent / undo them all. | Every write path |
| Savepoint | A smaller transaction inside a bigger one that can be undone on its own. | `begin_nested()` in demos |
| Order | A confirmed purchase request: PENDING until tickets are issued. | `orders` table |
| Ticket | One issued admission, with a unique number in its tier (and a seat, for reserved seating). | `tickets` table |
| Partial unique index | A uniqueness rule that only applies to rows matching a condition (e.g. `status = 'ISSUED'`). | `uq_tickets_issued_seat`, `uq_tickets_issued_number` |
| UUID primary key | A random 128-bit id instead of 1, 2, 3...; unguessable and safe to show in URLs. | `orders.id` |

## Mock payments (S3.2)

| Term | Meaning | Where it appears |
|---|---|---|
| Payment provider | A company that moves money (e.g. Stripe); here a fake in-process stand-in. | `MockPaymentProvider` |
| Payment token | An opaque string standing for a card, issued by the provider; our server never sees card numbers. | `tok_ok`, `tok_declined`, `tok_unavailable` |
| Charge / refund | Take money for a token / give it back. | `charge()`, `refund()` |
| 402 Payment Required | The HTTP status for "the payment didn't go through". | `PaymentDeclined` |
| Mock / test double | A stand-in for a real dependency that behaves predictably in tests. | The whole `payments.py` |
| Failure injection | Deliberately making a dependency fail some of the time, to test the failure paths. | `PAYMENT_FAILURE_RATE` |

## Confirming (S3.3)

| Term | Meaning | Where it appears |
|---|---|---|
| Confirm | Turning a hold into a PENDING order: check the hold, charge, then write the order + outbox. | `POST /holds/{id}/confirm` |
| CONFIRMING | The hold status while it's being bought; the expiry sweeper leaves it alone. | `consume_hold.lua`, `holds:confirming` |
| Outbox | A table of "work to do after this commit", written in the same transaction as the data. | `outbox_events` |
| Outbox pattern | Write data + outbox row atomically; a relay publishes the row later, so follow-up work is never lost. | S3.3 (write), S4.1 (relay) |
| 202 Accepted | "Got it, still working on it" (tickets aren't issued yet). | Confirm response |
| 410 Gone | "It existed but is no longer available." | `HoldExpired` |
| Compensating action | Undoing an earlier step when a later one fails (revert the hold, refund the payment). | `confirm_hold()` |
| Row lock (`SELECT ... FOR UPDATE`) | Makes concurrent transactions touching the same row take turns. | Locking the user's row at confirm |
| JSONB | Postgres's binary JSON column type: flexible structured data, queryable. | `outbox_events.payload` |
| `WRONGTYPE` | Redis's error for using a command on the wrong data type (e.g. HMGET on a string). | The S3.3 robustness fix |

## The outbox relay (S4.1)

| Term | Meaning | Where it appears |
|---|---|---|
| Relay | The background task that copies committed outbox rows to the Redis Stream. | `app/worker/relay.py` |
| Redis Stream | An append-only log inside Redis; each entry gets an id like `1794216930353-0` (milliseconds-sequence) and holds a small map of fields. | `stream:orders` |
| `XADD` | The Redis command that appends one entry to a stream. | `relay_batch()` |
| `SKIP LOCKED` | Added to `FOR UPDATE`: rows another transaction has locked are skipped instead of waited for. | The relay's SELECT |
| At-least-once delivery | Every message is delivered, but occasionally more than once, so receivers must handle duplicates. | Publish, then mark PUBLISHED |
| Batch | Handling up to N items per pass (here 50) instead of one per query. | `BATCH_SIZE` |
| `asyncio.TaskGroup` | Runs several async tasks at once and waits for all of them. | `app/worker/main.py` |

## Relay retries (S4.2)

| Term | Meaning | Where it appears |
|---|---|---|
| Exponential backoff | Waiting twice as long after each failure (1 s, 2 s, 4 s ...), up to a cap. | `RetryPolicy.delay_after()` |
| Permanent vs transient failure | Permanent: retrying will fail the same way. Transient: it may work later. | `PermanentError`, `record_failure()` |
| DEAD (dead letter) | A message given up on after too many failures, kept for a human to look at. | `outbox_events.status` |
| Poison message | A message that fails every time it's processed; without care it blocks or loops forever. | Test 8 |
| Retention | How long finished records are kept before deletion (here 24 h for PUBLISHED rows). | `delete_old_published()` |

## Redis Streams (S4.3)

| Term | Meaning | Where it appears |
|---|---|---|
| Consumer group | A named reader of a stream that remembers its position and hands each entry to exactly one of its members. | `order-workers` |
| Consumer | One member of a group (here, one worker process, named hostname-pid). | `consumer_name()` |
| `XREADGROUP` | Read entries as a group member; `>` means "ones nobody in the group has had yet". | `read_new_entries()` |
| `XACK` | Tell the group an entry is done, removing it from the pending list. | `consume_batch()` |
| Pending entries list (PEL) | Entries handed out but not yet acknowledged, with who has them. | `XPENDING`, S4.6 retries |
| `MKSTREAM` | Create the stream when creating the group, if it doesn't exist yet. | `ensure_group()` |
| Blocking read | Redis holds the request open until data arrives or a timeout passes. | `BLOCK 1000` |

## Idempotent processing (S4.4)

| Term | Meaning | Where it appears |
|---|---|---|
| Idempotent consumer | A message handler that does the same thing whether a message arrives once or many times. | `run_once()` |
| De-duplication key | The value that identifies "the same message" across copies (here the outbox id). | `processed_messages.message_id` |
| `ON CONFLICT DO NOTHING` | Postgres: if this insert would break a unique rule, insert nothing instead of raising an error. | `claim_message()` |
| Claim | Recording "I'm handling this message" so nobody else does. | `claim_message()` |

## Issuing tickets (S4.5)

| Term | Meaning | Where it appears |
|---|---|---|
| Backstop | A last safety check that catches what earlier layers missed. | The conditional UPDATE on `tiers` |
| Conditional UPDATE | An UPDATE whose WHERE clause includes the rule (`sold + q <= capacity`), so the check and the write are one atomic step. | `TAKE_SEATS` |
| `RETURNING` | Postgres: send back values from the rows just changed, without another query. | `next_number` |
| Invariant | A rule that must always be true (here: sold never exceeds capacity). | `InvariantViolation` |
| Defence in depth | Several independent layers, so one failing doesn't cause damage. | Lua, then UPDATE, then CHECK, then unique index |
| After-commit step | Work outside the database done only once the commit succeeded. | `finish_hold.lua`, `after_commit` |
| CONSUMED | Final hold status: its seats became tickets. | `finish_hold.lua` |

## Retries and dead letters (S4.6)

| Term | Meaning | Where it appears |
|---|---|---|
| Transient error | A failure that may go away if you try later. | `TransientError`, any non-permanent exception |
| Redelivery | Handing an unacknowledged message to a worker again. | `retry_stuck()` |
| `XPENDING` (with IDLE) | Lists unacknowledged entries with idle time and delivery count. | `retry_stuck()` |
| `XCLAIM` | Takes over a pending entry for another consumer; `min_idle_time` stops two workers grabbing it at once. | `retry_stuck()` |
| Dead-letter queue | Where messages go when the system gives up on them, for a human to look at. | `stream:orders:dead` |
| Compensation | Undoing earlier steps when a process can't finish (fail the order, release the seats). | `fail_order_and_release_hold()` |
| FAILED | Order status: it could not be fulfilled and its seats were given back. | `orders.status` |

## Relay crashes (S4.7)

| Term | Meaning | Where it appears |
|---|---|---|
| Crash point | A specific moment a process could die; each must leave a state the system can recover from. | Test 10 |
| Exactly-once effect | Messages may arrive more than once, but the result (tickets issued) happens once. | Outbox, then `run_once` |
| `os._exit` | Ends a Python process immediately: no cleanup, no `finally`, like a real crash. | The S4.7 demo |
| `pg_terminate_backend` | A Postgres function that kills another session; its transaction is rolled back and its locks are freed. | Test 10 |

## Reconcile (S5.1)

| Term | Meaning | Where it appears |
|---|---|---|
| Reconcile | Comparing a copy (the Redis counter) with the source of truth and fixing the copy. | `POST /admin/events/{id}/reconcile` |
| Drift | When a cached value slowly stops matching the truth. | `before` vs `after` |
| Snapshot | A view of the data as of one instant; one SQL statement always sees one. | `TIER_SNAPSHOT` |
| `GETDEL` | Redis: read a key and delete it in one atomic step. | `reconcile_tier()` |

## Surviving a Redis flush (S5.2)

| Term | Meaning | Where it appears |
|---|---|---|
| `FLUSHALL` / `FLUSHDB` | Redis commands that delete every key (all databases / the current one). | Test 11, the S5.2 demo |
| Re-drive (re-queue) | Sending work again from the source of truth because the in-flight copy may be lost. | `REQUEUE_PENDING_ORDERS` |
| Self-healing | A loop that notices a broken state and repairs it without a restart. | `run_consumer` re-creating its group |
| Throwaway container | A container started for one run and removed afterwards, so nothing real is touched. | testcontainers in tests and the S5.2 demo |

## Cancellation (S5.3)

| Term | Meaning | Where it appears |
|---|---|---|
| CANCELLED | Order and ticket status after a cancel; the seats are free again, the numbers stay used. | `cancel_order()` |
| Marker key | A small Redis key that records "this was done", so a repeated step can tell and skip. | `returned:{order_id}` |
| Forced interleaving | A test that pauses one operation at a chosen point until another catches up, so a race happens every run. | Test 13 |

## Reserved seating (S6.1)

| Term | Meaning | Where it appears |
|---|---|---|
| Reserved seating | Every ticket is for a specific seat, chosen by the buyer. | `SeatingType.RESERVED`, `seats` table |
| General admission | Tickets are for a tier only; no specific seat. | `SeatingType.GENERAL_ADMISSION` |
| Seat map | The list of an event's seats and whether each is free, held or sold. | `GET /events/{id}/seats` |
| Foreign key | A column that must match an existing row in another table. | `tickets.seat_id -> seats.id` |
| `MGET` | Redis: read many keys in one round trip. | `held_seat_ids()` |

## Holding seats (S6.2)

| Term | Meaning | Where it appears |
|---|---|---|
| All-or-nothing | Either every part of a request happens, or none of it. | `reserve_seats.lua` |
| Seat key | `seat:{event}:{seat_id}`: exists while a hold has the seat; its value is the hold id. | Holds, release, seat map |
| Sold set | `sold:{event}`: seat ids that can never be held again, plus a `built` marker. | `reserve_seats.lua`, `rebuild_sold_set()` |
| `SISMEMBER` / `SADD` | Redis: test whether a set contains a value / add values to a set. | The sold set |

## Buying seats (S6.2b)

| Term | Meaning | Where it appears |
|---|---|---|
| `integer[]` (ARRAY) | A Postgres column holding a list of numbers. | `orders.seat_ids` |
| Partial unique index | A uniqueness rule that only applies to rows matching a condition (here: ISSUED tickets). | `uq_tickets_issued_seat` |
| `MULTI` / `EXEC` | Redis transaction: queued commands run together, with nothing in between. | `rebuild_sold_set(force=True)` |
| `SREM` | Redis: remove values from a set. | Cancel, failed orders |

## Rate limiting (S7.1)

| Term | Meaning | Where it appears |
|---|---|---|
| Rate limit | A cap on how many requests a caller may make in a period. | `rate_limit.lua` |
| Sliding window | Counts requests in the last N seconds from *now*, rather than resetting on the minute. | `rate_limit.lua` |
| 429 Too Many Requests | "Slow down"; `Retry-After` says how many seconds to wait. | `RateLimited` |
| Fail open / fail closed | When a safety check can't run: let the request through (open) or refuse it (closed). | Login with Redis down |
| Credential stuffing | Trying leaked email/password pairs across many accounts. | Per-IP login limit |
