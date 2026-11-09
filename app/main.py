"""Creates the FastAPI application object that every API request goes through.

uvicorn imports `app` from here and serves it:
`uv run python -m uvicorn app.main:app`.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.body_limit import BodySizeLimitMiddleware
from app.api.errors import register_error_handlers
from app.api.events import router as events_router
from app.api.events_public import router as public_events_router
from app.api.health import router as health_router
from app.api.holds import router as holds_router
from app.api.live import LiveUpdates
from app.api.live import router as live_router
from app.api.me import router as me_router
from app.api.metrics import RequestMetricsMiddleware
from app.api.metrics import router as metrics_router
from app.api.orders import router as orders_router
from app.api.request_context import RequestContextMiddleware
from app.core.log_setup import configure_logging
from app.core.settings import get_settings
from app.db.session import create_db_engine, create_session_factory
from app.redis.client import create_redis_client
from app.services.payments import MockPaymentProvider

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open shared connections once at startup and close them at shutdown.

    Everything before `yield` runs when the server starts, and everything
    after it runs when the server stops.
    """
    # JSON logs with the correlation id (S8.2b). Here, not at import time:
    # uvicorn has set up its own loggers by now, and tests (which don't run
    # the lifespan) keep pytest's log capture untouched.
    configure_logging(settings.log_format)
    # None of these connect yet; they only set up pools that connect on first use.
    app.state.db_engine = create_db_engine()
    app.state.session_factory = create_session_factory(app.state.db_engine)
    app.state.redis = create_redis_client()
    # A mock: there are no real payments in this project (CLAUDE.md section 2).
    app.state.payments = MockPaymentProvider(failure_rate=settings.payment_failure_rate)
    # One shared Redis subscription for every live-update viewer (S7.3).
    app.state.live = LiveUpdates(app.state.redis)
    await app.state.live.start()
    yield
    await app.state.live.stop()
    await app.state.redis.aclose()
    await app.state.db_engine.dispose()


def api_docs_enabled(environment: str) -> bool:
    """The interactive API docs: handy locally, off in production.

    In production they would map the whole API (including admin routes) for anyone.
    """
    return environment != "production"


docs = api_docs_enabled(settings.environment)
app = FastAPI(
    title=settings.app_name,
    description="A ticket booking backend that never oversells under heavy concurrency.",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if docs else None,
    redoc_url="/redoc" if docs else None,
    openapi_url="/openapi.json" if docs else None,
)
register_error_handlers(app)
# Only the listed browser origins may call the API cross-origin. No cookies are
# used (tokens travel in the Authorization header), so credentials stay off.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    expose_headers=["Retry-After", "X-Correlation-ID"],
)
# Times every request (S8.2). Added before the body limit, so it sits inside
# it: refused oversized bodies are not timed, everything else is.
app.add_middleware(RequestMetricsMiddleware)
# Outermost layer: oversized bodies are refused before any route reads them.
app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_body_bytes)
# Outside even that: every request, refused or not, gets a correlation id
# and one access-log line (S8.2b).
app.add_middleware(RequestContextMiddleware)
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(me_router)
app.include_router(events_router)
app.include_router(public_events_router)
app.include_router(holds_router)
app.include_router(orders_router)
app.include_router(admin_router)
app.include_router(live_router)
# Internal only: nginx never routes /metrics to the outside (S8.1).
app.include_router(metrics_router)


# `async def` lets the server handle other requests while this one waits on
# slow things (databases, Redis).
@app.get("/")
async def read_root() -> dict[str, str]:
    """A hello endpoint that proves the server is up."""
    return {"message": "Hello from seatsurge"}
