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
