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
