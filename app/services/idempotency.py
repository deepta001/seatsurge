"""Idempotency keys: a retried request returns the first answer instead of doing the work again.

The flow for one key:
  begin()    claims the key atomically (SET NX), or returns the stored answer
  ...the real work...
  complete() stores the final answer for 24 hours
  abandon()  frees the key if the work failed in a way worth retrying
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis

from app.core.errors import IdempotencyKeyReused, RequestInProgress
from app.redis.keys import idempotency_key

# Stored answers live for 24 hours (CLAUDE.md section 5).
STORED_RESPONSE_SECONDS = 24 * 60 * 60
# A claim lasts only 30 s, so if the server crashes mid-request the key frees
# itself quickly and the client's retry can go through.
IN_PROGRESS_SECONDS = 30


@dataclass(frozen=True)
class StoredResponse:
    status_code: int
    body: dict[str, Any]


def request_fingerprint(route: str, body: dict[str, Any]) -> str:
    """A hash of what was asked for. sort_keys makes key order irrelevant."""
    canonical = json.dumps({"route": route, "body": body}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


async def begin(redis: Redis, user_id: int, key: str, fingerprint: str) -> StoredResponse | None:
    """Claim the key. Returns None if the caller should do the work now.

    Returns the stored response if this exact request already finished.
    Raises IdempotencyKeyReused (different request, same key) or
    RequestInProgress (the first attempt is still running).
    """
    redis_key = idempotency_key(user_id, key)
    claim = json.dumps({"state": "in_progress", "fingerprint": fingerprint})
    # SET ... NX is atomic: of several simultaneous retries, exactly one wins
    # the claim; the others fall through and read what's there.
    if await redis.set(redis_key, claim, nx=True, ex=IN_PROGRESS_SECONDS):
        return None

    raw = await redis.get(redis_key)
    if raw is None:
        # The claim expired between our SET and GET. Rare; ask for a retry.
        raise RequestInProgress()
    record = json.loads(raw)
    if record["fingerprint"] != fingerprint:
        raise IdempotencyKeyReused()
    if record["state"] == "in_progress":
        raise RequestInProgress()
    return StoredResponse(status_code=record["status_code"], body=record["body"])


async def complete(
    redis: Redis, user_id: int, key: str, fingerprint: str, response: StoredResponse
) -> None:
    """Store the final answer, replacing the claim, for 24 hours."""
    record = {
        "state": "done",
        "fingerprint": fingerprint,
        "status_code": response.status_code,
        "body": response.body,
    }
    await redis.set(idempotency_key(user_id, key), json.dumps(record), ex=STORED_RESPONSE_SECONDS)


async def abandon(redis: Redis, user_id: int, key: str) -> None:
    """Release the claim without storing anything, so a retry can try again."""
    await redis.delete(idempotency_key(user_id, key))
