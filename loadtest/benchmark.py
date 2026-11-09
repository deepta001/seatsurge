"""Repeat the headline load test and collect the numbers for docs/benchmarks.md (S8.5).

    uv run --group load python -m loadtest.benchmark --runs 5 --label baseline

Each run: prepare a fresh sale -> Locust (all users at once) -> wait for the
queue -> verify_consistency -> read the numbers -> clean up. Two views of
latency are recorded:

  - client: what Locust measured (includes the client's own queueing, on
    the same laptop as the system);
  - server: what the api replicas measured themselves (Prometheus histogram,
    request in -> response out), plus Redis script time as the app sees it.

A run whose consistency check fails is reported as such; numbers are never
invented or smoothed. Results go to loadtest/results/benchmark-<label>.json.
"""

import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "loadtest" / "results"
PROMETHEUS = "http://127.0.0.1:9090/api/v1/query"
WINDOW = "15s"  # just this run's traffic: runs are further apart than this
STATS_FILE = RESULTS / "last-stats.json"
ENDPOINTS = {"hold": "POST /events/[id]/holds", "confirm": "POST /holds/[id]/confirm"}


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True)


def python(*args: str) -> subprocess.CompletedProcess[str]:
    return run([sys.executable, "-m", *args])


def locust_stats() -> dict[str, Any]:
    """Locust's per-endpoint numbers (ms) for every request, saved by the locustfile at the end.

    Not its --csv files: those missed up to 215 of 1,100 requests when the
    test stopped itself (found in S8.5).
    """
    saved = json.loads(STATS_FILE.read_text(encoding="utf-8"))
    names = {v: k for k, v in ENDPOINTS.items()}
    return {names.get(name, name): numbers for name, numbers in saved.items()}


def prometheus(query: str) -> float | None:
    result = httpx.get(PROMETHEUS, params={"query": query}, timeout=10).json()["data"]["result"]
    if not result or result[0]["value"][1] in ("NaN", "+Inf"):
        return None
    return round(float(result[0]["value"][1]) * 1000, 1)  # seconds -> ms


def server_stats() -> dict[str, float | None]:
    """Percentiles the api replicas recorded themselves, over the last WINDOW."""

    def quantile(q: float, metric: str, selector: str) -> str:
        return (
            f"histogram_quantile({q}, sum by (le) "
            f"(increase({metric}_bucket{{{selector}}}[{WINDOW}])))"
        )

    holds = 'route="/events/{event_id}/holds"'
    return {
        "hold_p50_ms": prometheus(quantile(0.5, "http_request_duration_seconds", holds)),
        "hold_p99_ms": prometheus(quantile(0.99, "http_request_duration_seconds", holds)),
        "rate_limit_script_p99_ms": prometheus(
            quantile(0.99, "redis_script_duration_seconds", 'script="rate_limit"')
        ),
        "reserve_script_p99_ms": prometheus(
            quantile(0.99, "redis_script_duration_seconds", 'script="reserve_tier"')
        ),
    }


def one_run(n: int, label: str, users: int, seats: int, host: str) -> dict[str, Any]:
    prepared = python("loadtest.prepare", "--seats", str(seats), "--users", str(users))
    if prepared.returncode:
        raise SystemExit(prepared.stdout + prepared.stderr)
    event_id = json.loads((ROOT / "loadtest" / "run.json").read_text(encoding="utf-8"))["event_id"]
    prefix = RESULTS / f"benchmark-{label}-{n}"
    try:
        started = time.monotonic()
        locust = run(
            [
                sys.executable,
                "-m",
                "locust",
                "-f",
                "loadtest/locustfile.py",
                "--headless",
                "-u",
                str(users),
                "-r",
                str(users),
                "--run-time",
                "3m",
                "--only-summary",
                "--host",
                host,
                "--csv",
                str(prefix),
            ]
        )
        locust_seconds = time.monotonic() - started
        outcomes = {
            line.strip().rsplit(None, 1)[0]: int(line.strip().rsplit(None, 1)[1])
            for line in locust.stdout.splitlines()
            if line.startswith("  ") and line.strip().rsplit(None, 1)[-1].isdigit()
        }
        verified = python("scripts.verify_consistency", "--event", str(event_id), "--wait", "60")
        time.sleep(6)  # let Prometheus scrape the replicas once more (every 5 s)
        return {
            "run": n,
            "outcomes": outcomes,
            "locust_process_seconds": round(locust_seconds, 2),
            "client": locust_stats(),
            "server": server_stats(),
            "consistent": verified.returncode == 0,
            "verify": verified.stdout.strip().splitlines(),
        }
    finally:
        python("loadtest.cleanup")


def summary(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Median across runs of each number (and min/max, to show the spread)."""

    def spread(values: list[float]) -> dict[str, float]:
        return {"median": statistics.median(values), "min": min(values), "max": max(values)}

    def client(endpoint: str, field: str) -> dict[str, float]:
        return spread([r["client"][endpoint][field] for r in runs])

    def server(field: str) -> dict[str, float]:
        return spread([r["server"][field] for r in runs if r["server"][field] is not None])

    return {
        "runs": len(runs),
        "all_consistent": all(r["consistent"] for r in runs),
        "failed_requests": sum(r["client"]["Aggregated"]["failures"] for r in runs),
        **{f"client_hold_{f}": client("hold", f) for f in ("p50_ms", "p95_ms", "p99_ms", "max_ms")},
        **{f"client_confirm_{f}": client("confirm", f) for f in ("p50_ms", "p95_ms", "p99_ms")},
        "client_requests_per_s": client("Aggregated", "requests_per_s"),
        **{f"server_{f}": server(f) for f in runs[0]["server"]},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Repeat the headline load test.")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--users", type=int, default=1000)
    parser.add_argument("--seats", type=int, default=100)
    parser.add_argument("--host", default="http://127.0.0.1:8080")
    parser.add_argument("--label", default="baseline")
    args = parser.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)

    runs = []
    for n in range(1, args.runs + 1):
        result = one_run(n, args.label, args.users, args.seats, args.host)
        runs.append(result)
        hold = result["client"]["hold"]
        print(
            f"run {n}: consistent={result['consistent']} outcomes={result['outcomes']} "
            f"hold p50/p95/p99={hold['p50_ms']:.0f}/{hold['p95_ms']:.0f}/{hold['p99_ms']:.0f} ms "
            f"server={result['server']}",
            flush=True,
        )
    report = {
        "label": args.label,
        "users": args.users,
        "seats": args.seats,
        "summary": summary(runs),
        "runs": runs,
    }
    out = RESULTS / f"benchmark-{args.label}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print(f"saved {out}")


if __name__ == "__main__":
    main()
