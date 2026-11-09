"""Per-request context: the correlation id, the X-Correlation-ID header, and the access log.

Every request gets an id: nginx's (it sets X-Correlation-ID to its own
$request_id), or a fresh one if the header is missing or unsafe. While the
request runs, every log line carries it; the response returns it; any
outbox row the request writes stores it (S8.2b).
"""

import logging
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.metrics import route_template
from app.core.correlation import correlation_scope, usable_correlation_id

logger = logging.getLogger("app.access")

HEADER = b"x-correlation-id"
# Health checks run every few seconds; logging each would drown everything else.
QUIET_ROUTES = {"/health/live", "/health/ready", "/metrics"}


def incoming_id(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name == HEADER:
            text: str = value.decode("latin-1")
            return text
    return None


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        correlation_id = usable_correlation_id(incoming_id(scope))
        # Also kept on the request, for the 500 handler: it runs OUTSIDE this
        # middleware, after the logging context below has been removed.
        scope.setdefault("state", {})["correlation_id"] = correlation_id
        started = time.perf_counter()
        status = 500  # what the client gets if the app crashes before answering

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = list(message.get("headers", []))
                if not any(name.lower() == HEADER for name, _ in headers):
                    headers.append((HEADER, correlation_id.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        with correlation_scope(correlation_id):
            try:
                await self.app(scope, receive, send_with_id)
            finally:
                route = route_template(scope)
                if route not in QUIET_ROUTES:
                    logger.info(
                        "request",
                        extra={
                            "method": scope["method"],
                            "path": scope["path"],
                            "route": route,
                            "status": status,
                            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                        },
                    )
