"""Chaos runs (S8.4): the headline load test while something breaks, on a throwaway stack.

    uv run --group load python -m loadtest.chaos kill-worker
    uv run --group load python -m loadtest.chaos flush-redis
    uv run --group load python -m loadtest.chaos two-workers

Each run starts a SECOND copy of the system (Compose project
"seatsurge-chaos", ports and network from loadtest/chaos.env), so flushing
its Redis or killing its worker never touches the dev stack. Then:

  1. prepare one sale (100 seats, 1,000 buyers) on that copy;
  2. start Locust through its nginx, ramping up over ~5 s;
  3. at a chosen moment of the sale (by its state, not a timer), break something:
     - kill-worker: once 10 orders are CONFIRMED, SIGKILL the worker (no clean
       shutdown), start it 5 s later;
     - flush-redis: once 30 orders exist, FLUSHALL Redis (every hold, counter
       and stream lost);
       after the sale an admin runs reconcile, as the runbook says;
     - two-workers: nothing breaks; two worker containers share the work;
  4. wait for the queue to drain, run scripts/verify_consistency.py;
  5. tear the copy down, volumes included.

Exit code: verify_consistency's (0 = consistent).
"""

import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAOS_ENV = ROOT / "loadtest" / "chaos.env"
COMPOSE = [
    "docker",
    "compose",
    "-p",
    "seatsurge-chaos",
    "--env-file",
    ".env",
    "--env-file",
    str(CHAOS_ENV),
]
SERVICES = ["postgres", "redis", "migrate", "api", "worker", "nginx"]
SCENARIOS = ("kill-worker", "flush-redis", "two-workers")
USERS, SEATS, SPAWN_RATE = 1000, 100, 200


def env_file(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def chaos_environment() -> dict[str, str]:
    """This process's environment, with the database and Redis URLs of the chaos copy."""
    secrets, ports = env_file(ROOT / ".env"), env_file(CHAOS_ENV)
    return {
        **os.environ,
        "DATABASE_URL": (
            f"postgresql+asyncpg://seatsurge:{secrets['POSTGRES_PASSWORD']}"
            f"@127.0.0.1:{ports['POSTGRES_PORT']}/seatsurge"
        ),
        "REDIS_URL": f"redis://:{secrets['REDIS_PASSWORD']}@127.0.0.1:{ports['REDIS_PORT']}/0",
    }


def run(command: list[str], env: dict[str, str] | None = None, check: bool = True) -> int:
    print(f"$ {' '.join(command)}", flush=True)
    return subprocess.run(command, cwd=ROOT, env=env, check=check).returncode


def compose(*args: str, check: bool = True) -> int:
    return run([*COMPOSE, *args], check=check)


ORDER_COUNTS = "SELECT count(*) FILTER (WHERE status = 'CONFIRMED') || ' ' || count(*) FROM orders"


def order_counts() -> tuple[int, int]:
    """(CONFIRMED orders, all orders) in the chaos database, read with psql in its container."""
    result = subprocess.run(
        [
            *COMPOSE,
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "seatsurge",
            "-d",
            "seatsurge",
            "-tAc",
            ORDER_COUNTS,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    confirmed, total = result.stdout.split()
    return int(confirmed), int(total)


def wait_until(condition: str, ready: Callable[[int, int], bool], timeout: float = 60) -> str:
    """Poll the order counts until `ready(confirmed, total)`; describe the moment it happened."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        confirmed, total = order_counts()
        if ready(confirmed, total):
            return f"{condition}: {total} orders placed, {confirmed} CONFIRMED by the worker"
        time.sleep(0.05)
    return f"{condition}: not reached within {timeout:.0f} s (chaos applied anyway)"


def break_something(scenario: str, log: list[str]) -> None:
    """Runs beside Locust: wait for the right moment, then cause the scenario's failure.

    The moment is chosen by STATE, not by a timer (a timer missed the action
    in the first S8.4 run: the sale is over in a few seconds).
    """
    if scenario == "kill-worker":
        # Mid-stream: the worker has confirmed some orders and has more to do.
        log.append(wait_until("SIGKILL worker", lambda confirmed, total: confirmed >= 10))
        compose("kill", "-s", "SIGKILL", "worker")
        confirmed, total = order_counts()
        log.append(f"just after the kill: {total - confirmed} orders waiting (PENDING)")
        time.sleep(5)
        confirmed, total = order_counts()
        log.append(f"5 s later, still {total - confirmed} PENDING; starting the worker again")
        compose("start", "worker")
    elif scenario == "flush-redis":
        # Mid-sale: holds live, orders PENDING and CONFIRMED, buyers still arriving.
        log.append(wait_until("FLUSHALL Redis", lambda confirmed, total: total >= 30))
        compose("exec", "-T", "redis", "redis-cli", "FLUSHALL")


def reconcile(env: dict[str, str], run_details: dict[str, object], nginx_port: str) -> None:
    """What an operator does after losing Redis: POST /admin/events/{id}/reconcile."""
    os.environ.update({"DATABASE_URL": env["DATABASE_URL"], "REDIS_URL": env["REDIS_URL"]})
    import httpx  # imported here: settings must see the chaos URLs first

    from app.core.tokens import create_access_token
    from app.db.models import UserRole

    token = create_access_token(int(str(run_details["admin_id"])), UserRole.ADMIN)
    response = httpx.post(
        f"http://127.0.0.1:{nginx_port}/admin/events/{run_details['event_id']}/reconcile",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    print(f"reconcile -> {response.status_code} {response.text}", flush=True)


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in SCENARIOS:
        print(f"usage: python -m loadtest.chaos {{{','.join(SCENARIOS)}}}")
        return 64
    scenario = sys.argv[1]
    env = chaos_environment()
    nginx_port = env_file(CHAOS_ENV)["NGINX_PORT"]
    workers = "2" if scenario == "two-workers" else "1"
    log: list[str] = []
    try:
        compose("up", "-d", "--build", "--wait", "--scale", f"worker={workers}", *SERVICES)
        run(
            [
                sys.executable,
                "-m",
                "loadtest.prepare",
                "--seats",
                str(SEATS),
                "--users",
                str(USERS),
            ],
            env,
        )
        run_details = json.loads((ROOT / "loadtest" / "run.json").read_text(encoding="utf-8"))

        chaos = threading.Thread(target=break_something, args=(scenario, log))
        chaos.start()
        started = time.monotonic()
        run(
            [
                sys.executable,
                "-m",
                "locust",
                "-f",
                "loadtest/locustfile.py",
                "--headless",
                "-u",
                str(USERS),
                "-r",
                str(SPAWN_RATE),
                "--run-time",
                "3m",
                "--only-summary",
                "--host",
                f"http://127.0.0.1:{nginx_port}",
                "--csv",
                f"loadtest/results/chaos-{scenario}",
            ],
            env,
            check=False,  # under chaos some requests fail on purpose; verify decides
        )
        chaos.join()
        log.append(f"Locust finished after {time.monotonic() - started:.1f} s")

        if scenario == "flush-redis":
            reconcile(env, run_details, nginx_port)
        verdict = run(
            [
                sys.executable,
                "-m",
                "scripts.verify_consistency",
                "--event",
                str(run_details["event_id"]),
                "--wait",
                "120",
            ],
            env,
            check=False,
        )
        if scenario == "two-workers":
            for n in (1, 2):
                logs = subprocess.run(
                    ["docker", "logs", f"seatsurge-chaos-worker-{n}"],
                    capture_output=True,
                    text=True,
                )
                issued = (logs.stdout + logs.stderr).count("issued tickets")
                log.append(f"worker-{n} issued tickets for {issued} order(s)")
        print("\nChaos log:\n  " + "\n  ".join(log))
        print(f"verify_consistency exit code: {verdict}")
        return verdict
    finally:
        compose("down", "-v", check=False)  # throwaway: containers, network AND volumes
        for leftover in ("run.json", "created.json"):
            (ROOT / "loadtest" / leftover).unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
