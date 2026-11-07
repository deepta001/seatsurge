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
