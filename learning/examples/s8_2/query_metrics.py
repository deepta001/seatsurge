"""S8.2 demo: ask Prometheus the questions the Grafana dashboard asks.

With the full stack up (docker compose up -d --build), after some traffic:

    uv run python -m learning.examples.s8_2.query_metrics

Prometheus has scraped every api replica and the worker; these queries add
them up. Read-only: it changes nothing.
"""

import httpx

PROMETHEUS = "http://127.0.0.1:9090/api/v1/query"
HOLD_BUCKETS = 'http_request_duration_seconds_bucket{route="/events/{event_id}/holds"}'


def hold_latency(quantile: float, name: str) -> str:
    """One percentile of hold request latency over the last 5 minutes, labelled `name`."""
    estimate = f"histogram_quantile({quantile}, sum by (le) (rate({HOLD_BUCKETS}[5m])))"
    return f'label_replace({estimate}, "q", "{name}", "", "")'


QUERIES = {
    "holds created (all replicas)": "sum(holds_created_total)",
    "holds created per replica": "sum by (instance) (holds_created_total)",
    "holds rejected, by reason": "sum by (reason) (holds_rejected_total)",
    "orders placed / confirmed / failed": (
        'label_replace(sum(orders_placed_total), "kind", "placed", "", "")'
        ' or label_replace(sum(orders_confirmed_total), "kind", "confirmed", "", "")'
        ' or label_replace(sum(orders_failed_total) or vector(0), "kind", "failed", "", "")'
    ),
    "invariant violations (must be 0)": "sum(invariant_violations_total)",
    "outbox pending / stream pending": (
        'label_replace(sum(outbox_pending), "kind", "outbox", "", "")'
        ' or label_replace(sum(stream_pending_messages), "kind", "stream", "", "")'
    ),
    "hold request p50 / p99 (s), last 5 min": (
        hold_latency(0.5, "p50") + " or " + hold_latency(0.99, "p99")
    ),
    "Redis script p99 (s), last 5 min": (
        "histogram_quantile(0.99, sum by (le, script) "
        "(rate(redis_script_duration_seconds_bucket[5m])))"
    ),
}


def describe(metric: dict[str, str]) -> str:
    labels = {k: v for k, v in metric.items() if k not in ("__name__", "job")}
    return ",".join(f"{k}={v}" for k, v in sorted(labels.items())) or "total"


def main() -> None:
    with httpx.Client(timeout=10) as http:
        for title, query in QUERIES.items():
            results = http.get(PROMETHEUS, params={"query": query}).json()["data"]["result"]
            print(title)
            if not results:
                print("   (no data yet)")
            for series in results:
                number = float(series["value"][1])
                print(f"   {describe(series['metric']):40} {number:.4g}")


if __name__ == "__main__":
    main()
