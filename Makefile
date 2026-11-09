# Shortcuts for the common commands (CLAUDE.md section 12). `make` is standard
# on Linux and macOS; on Windows, run the command shown under each target.
# Tools run as `python -m <tool>`, which also works where Windows Smart App
# Control blocks the .exe launchers in .venv.

SEATS ?= 100
USERS ?= 1000
HOST  ?= http://127.0.0.1:8080
PY    := uv run python -m

.PHONY: up down test lint load verify load-clean

# The whole system: Postgres, Redis, migrations, 3 api replicas, worker,
# nginx (port 8080), Prometheus (9090) and Grafana (3000).
up:
	docker compose up -d --build --wait

down:
	docker compose down

# Unit, integration, concurrency and adversarial tests (Docker must be running).
test:
	$(PY) pytest

lint:
	$(PY) ruff check .
	$(PY) ruff format --check .
	$(PY) mypy

# The headline test: USERS buyers on SEATS seats through nginx, then the
# consistency check. Needs `make up` first.
load:
	$(PY) loadtest.prepare --seats $(SEATS) --users $(USERS)
	uv run --group load python -m locust -f loadtest/locustfile.py --headless \
		-u $(USERS) -r $(USERS) --run-time 3m --host $(HOST) --csv loadtest/results/run
	$(PY) scripts.verify_consistency --wait 60

# Postgres and Redis agree, nothing oversold. Exit code 1 on any mismatch.
verify:
	$(PY) scripts.verify_consistency --wait 60

# Delete exactly what the last load run created.
load-clean:
	$(PY) loadtest.cleanup
