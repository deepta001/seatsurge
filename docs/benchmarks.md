# Benchmarks

Measured numbers only (CLAUDE.md section 1: correctness > clarity >
observability > speed). Every number here came from a run described below,
on the machine described below. Nothing is extrapolated, and percentiles are
reported as measured, including the spread between runs.

Measured on 2026-11-09 (S8.5).

## The test

The headline test from CLAUDE.md section 1:

- **1,000 simulated buyers compete for 100 seats** (one general-admission
  tier), all starting at the same instant (Locust spawn rate = user count).
- Every request goes through **nginx** (round robin) to **3 api replicas**;
  one worker container issues tickets.
- Each buyer tries once: `POST /events/{id}/holds` for 1 seat; if that
  returns 201, `POST /holds/{id}/confirm` (mock payment); then it stops.
  So each run sends exactly 1,100 requests: 1,000 holds and 100 confirms.
- The Redis counter starts **missing**, so the first wave also exercises the
  locked rebuild from Postgres (rule 4).
- After each run, `scripts/verify_consistency.py` waits for the queue to
  drain and compares Postgres with Redis.

Reproduce (stack up with `make up`):

```
uv run --group load python -m loadtest.benchmark --runs 5 --label baseline
```

Raw per-run results are written to `loadtest/results/benchmark-<label>.json`.

## The machine

Everything (the system AND the load generator) ran on one laptop:

| | |
|---|---|
| CPU | Intel Core Ultra 5 226V, 8 cores / 8 threads, 2.1 GHz base |
| RAM | 15.5 GB |
| Disk | WD PC SN5000S NVMe SSD, 512 GB |
| OS | Windows 11 Home (10.0.26200), on AC power, "Balanced" power plan |
| Docker | Docker Desktop, engine 29.9.2, Compose v5.6.1, WSL2 VM with 8 CPUs and 7.5 GiB |
| Images | postgres:16-alpine, redis:7-alpine, nginxinc/nginx-unprivileged:1.28-alpine, app on python:3.12-slim-bookworm |
| Load generator | Locust 2.47.0 (one process, FastHttpUser) on Windows, Python 3.12.10, through Docker Desktop's port forwarding |
| App settings | defaults: DB pool 5 + 10 per process, Redis pool 50 per process, hold TTL 5 min, JSON logs, metrics on |

## Results: 5 runs, 3 replicas (the committed configuration)

### Correctness (every run)

| | Each of the 5 runs |
|---|---|
| Holds granted / refused sold out | 100 / 900 |
| Orders confirmed / tickets issued | 100 / 100 |
| **Oversold** | **0** |
| Failed requests (anything other than 201/202/409) | 0 |
| `verify_consistency` | CONSISTENT (Postgres and Redis agree) |
| `invariant_violations_total` | 0 |

The same correctness held in the chaos runs (S8.4): worker SIGKILLed
mid-stream, Redis FLUSHALLed mid-sale, and two workers. See
`docs/failure-modes.md`.

### Latency as the client saw it (Locust), median of 5 runs (min to max)

| Request | p50 | p95 | p99 | max |
|---|---|---|---|---|
| Hold (`POST /events/{id}/holds`) | 2.2 s (2.0 to 2.7) | 2.9 s (2.7 to 3.4) | 3.0 s (2.8 to 3.5) | 3.0 s (2.9 to 3.6) |
| Confirm (`POST /holds/{id}/confirm`) | 1.5 s (1.4 to 1.7) | 2.1 s (1.6 to 2.7) | 2.4 s (1.7 to 2.9) | |

### Throughput

| | Median (min to max) |
|---|---|
| Requests per second over the sale | 356 (297 to 365) |
| Time for all 1,100 requests (1,100 / rate) | ~3.1 s |

### Latency as the api replicas measured it (Prometheus), median of 5 runs

| | Median (min to max) |
|---|---|
| Hold, p50 | ~1.7 s (1.6 to 1.7) |
| Hold, p99 | between 2.5 and 5 s (see note) |
| `rate_limit` script, p99, as the app experiences it | 0.20 s (0.18 to 0.94) |
| `reserve_tier` script, p99, as the app experiences it | 45 ms (38 to 137) |
| Every Lua script, inside Redis (`INFO commandstats`, 60,417 calls) | 52 us per call on average |

Note: these come from histogram buckets (..., 1, 2.5, 5 s), so a percentile
falling in the wide 2.5 to 5 s bucket is an estimate; the raw estimate
(~4.1 s) is above what the client measured and should be read only as
"between 2.5 and 5 s". The script times include waiting for a free Redis
connection and for the event loop, which is why they are far above Redis's
own ~52 us.

## Where the time goes

The latency above is NOT the cost of a hold. Redis does the atomic work in
~52 us. The seconds are queueing, measured three ways:

1. **Each api replica is CPU-bound during the burst.** `docker stats` showed
   every replica at ~100% of one core (93 to 120%), Postgres at ~120%, Redis
   at 17%, nginx at 14%. Each replica is one Python process with one event
   loop, and ~333 requests arrive at once, so they wait their turn for that
   core.
2. **Doubling the processes halves the server-side time.** An experiment with
   6 replicas (temporary override, DB overflow lowered so 6 x 10 + 15 = 75
   connections stays under Postgres's 100; not committed), 3 runs:

   | | 3 replicas | 6 replicas |
   |---|---|---|
   | Server hold p50 | ~1.7 s | ~0.73 s (0.41 to 1.39) |
   | Server hold p99 | 2.5 to 5 s | ~2.4 s |
   | Client hold p50 / p99 | 2.2 s / 3.0 s | 2.2 s / 3.1 s |
   | Correctness | 100 tickets, consistent | 100 tickets, consistent |

3. **But the client saw no improvement, because the laptop itself is
   saturated.** Total CPU across all 8 cores was 85 to 92% during the burst.
   The load generator, Docker Desktop's networking and the system share those
   cores, so more replicas only move CPU from one to another. Opening 1,000
   connections at once through Docker Desktop's port forwarding alone took
   ~0.9 s (p50) in an earlier probe (S8.1,
   `learning/examples/s8_1/connection_probe.py`), before any app work.

**Conclusion:** on one laptop, the end-to-end numbers measure the laptop as
much as the system. They show the system staying correct under a 1,000-user
burst; they are not a capacity figure. A fair throughput test needs the load
generator on a different machine from the system.

## What was found while measuring

- Locust's `--csv` files missed up to 215 of the 1,100 requests when the test
  stopped itself, so the first set of results was discarded and re-measured.
  The locustfile now saves its final statistics itself
  (`loadtest/results/last-stats.json`), and every run above counted all
  1,100 requests.
- An earlier guess (S8.2) blamed the Redis connection pool. The measurements
  above don't support that: Redis scripts are a small part of the time; CPU
  per replica is the main one.

## Not done (ideas, not measured)

- Run the load generator on another machine (or several Locust workers) to
  separate client cost from server cost.
- More server processes per replica (uvicorn workers) or more replicas, with
  the connection budget in `docs/design.md` recalculated.
- Cut CPU per hold request (it currently reads the event and tier from
  Postgres on every hold, and writes a JSON log line, metrics and an
  idempotency record).

None of these was changed: they would be separate, measured steps.
