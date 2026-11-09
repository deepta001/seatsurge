"""Every Prometheus metric the system exposes, defined in one place (CLAUDE.md section 10).

A metric is a number Prometheus reads ("scrapes") every few seconds from
each process's /metrics page and stores over time, so Grafana can graph it.
Counters only go up (Prometheus works out rates from them), gauges go up and
down, and histograms count observations into buckets (for p50/p95/p99).

Each process has its own copies: an api replica exposes the request and
hold metrics, the worker exposes the order, outbox and stream metrics.
Labels are always from a small fixed set (a route template, an error code),
never an id, so the number of time series stays small.
"""

from prometheus_client import Counter, Gauge, Histogram

# Seconds. Fine-grained at the low end, where a healthy request lands.
LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
# Lua scripts take well under a millisecond when Redis is healthy.
SCRIPT_BUCKETS = (0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 1.0)

# ---- API (each replica) ------------------------------------------------------

REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "Time to answer an HTTP request, by route template.",
    ["method", "route", "status"],
    buckets=LATENCY_BUCKETS,
)
HOLDS_CREATED = Counter("holds_created", "Holds created.")
HOLDS_REJECTED = Counter(
    "holds_rejected", "Hold requests refused, by reason (the error code).", ["reason"]
)
ORDERS_PLACED = Counter("orders_placed", "Holds confirmed into PENDING orders.")

# ---- Both processes ------------------------------------------------------------

REDIS_SCRIPT_DURATION = Histogram(
    "redis_script_duration_seconds",
    "Time to run one Lua script in Redis, by script.",
    ["script"],
    buckets=SCRIPT_BUCKETS,
)

# ---- Worker ---------------------------------------------------------------------

ORDERS_CONFIRMED = Counter("orders_confirmed", "Orders whose tickets were issued.")
ORDERS_FAILED = Counter("orders_failed", "Orders marked FAILED (their seats were released).")
DEAD_LETTERS = Counter(
    "dead_letters", "Stream messages moved to the dead-letter stream, by type.", ["type"]
)
HOLD_EXPIRIES = Counter("hold_expiries", "Abandoned holds released by the sweeper.")
# Must stay 0 in every test and in the load test (CLAUDE.md section 6): a
# database backstop refused something Redis let through.
INVARIANT_VIOLATIONS = Counter(
    "invariant_violations", "Database backstops that fired (should never happen)."
)

# Backlog gauges, refreshed every few seconds by the worker (app/worker/backlog.py).
OUTBOX_PENDING = Gauge("outbox_pending", "Outbox rows waiting to be published.")
OUTBOX_OLDEST_PENDING_AGE = Gauge(
    "outbox_oldest_pending_age_seconds", "Age of the oldest unpublished outbox row (0 if none)."
)
OUTBOX_DEAD = Gauge("outbox_dead", "Outbox rows the relay gave up on.")
STREAM_PENDING = Gauge(
    "stream_pending_messages", "Order messages delivered to a worker but not yet acked."
)
DEAD_LETTER_STREAM_LENGTH = Gauge(
    "dead_letter_stream_length", "Messages in the dead-letter stream (for a human to inspect)."
)
