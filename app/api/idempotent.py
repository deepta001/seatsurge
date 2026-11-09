"""Runs a route's work at most once per Idempotency-Key, replaying the stored answer on retry.

Shared by POST /events/{id}/holds and POST /holds/{id}/confirm. The storage
rules live in app/services/idempotency.py; this file is the HTTP glue.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel
from redis.asyncio import Redis

from app.core.errors import DomainError
from app.services import idempotency
from app.services.idempotency import StoredResponse


async def run_idempotently(
    redis: Redis,
    *,
    user_id: int,
    key: str,
    route: str,
    body: dict[str, Any],
    success_status: int,
    work: Callable[[], Awaitable[BaseModel]],
) -> JSONResponse:
    """Do `work` once for this (user, key, request); replay its answer on every retry."""
    fingerprint = idempotency.request_fingerprint(route, body)
    stored = await idempotency.begin(redis, user_id, key, fingerprint)
    if stored is not None:
        # This exact request already finished: replay its answer, do nothing new.
        return JSONResponse(
            status_code=stored.status_code,
            content=stored.body,
            headers={"Idempotent-Replayed": "true"},
        )

    try:
        result = await work()
    except DomainError as error:
        if error.status_code < 500:
            # A final answer (sold out, declined...): retries must see the same.
            await idempotency.complete(
                redis,
                user_id,
                key,
                fingerprint,
                StoredResponse(error.status_code, {"error": error.code, "message": error.message}),
            )
        else:
            # Temporary (e.g. 503): release the key so a retry can try again.
            await idempotency.abandon(redis, user_id, key)
        raise
    except Exception:
        await idempotency.abandon(redis, user_id, key)
        raise

    content = result.model_dump(mode="json")
    await idempotency.complete(
        redis, user_id, key, fingerprint, StoredResponse(success_status, content)
    )
    return JSONResponse(status_code=success_status, content=content)
