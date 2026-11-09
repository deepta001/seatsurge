"""Request timing for every route, and the /metrics page Prometheus reads (S8.2).

/metrics is for Prometheus on the internal network only: nginx answers it
with 404 (deploy/nginx.conf), so it is never reachable from outside.
"""

import time

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.metrics import REQUEST_DURATION

router = APIRouter(include_in_schema=False)

# Not timed: live streams last as long as someone watches (minutes, not
# milliseconds), and /metrics itself would only measure Prometheus.
UNTIMED_ROUTES = {"/events/{event_id}/stream", "/metrics"}


@router.get("/metrics")
async def metrics() -> Response:
    """Every metric of THIS process, in Prometheus's text format."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def route_template(scope: Scope) -> str:
    """'/events/{event_id}/holds', not '/events/42/holds': one series per route, not per id."""
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else "unmatched"


class RequestMetricsMiddleware:
    """Times each HTTP request and records it by method, route template and status."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = 500  # if the app crashes before answering, that's what the client gets

        async def send_and_remember_status(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_and_remember_status)
        finally:
            # The router has filled in scope["route"] by now (same dict object).
            route = route_template(scope)
            if route not in UNTIMED_ROUTES:
                REQUEST_DURATION.labels(scope["method"], route, str(status)).observe(
                    time.perf_counter() - started
                )
