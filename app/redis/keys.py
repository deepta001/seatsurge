"""Builds every Redis key name in one place (the key schema in CLAUDE.md section 5).

One spelling per key means the API, the worker and the sweeper can never
disagree about where something lives.
"""

# All hold expiry times, in one sorted set: score = expires_at in milliseconds.
HOLDS_EXPIRY_KEY = "holds:expiry"


def inventory_key(event_id: int, tier_id: int) -> str:
    """Live count of seats still available in one tier."""
    return f"inv:{event_id}:{tier_id}:avail"


def hold_key(hold_id: str) -> str:
    """One hold's record (a hash): user, event, tier, qty, status, expires_at."""
    return f"hold:{hold_id}"


def user_hold_key(event_id: int, user_id: int) -> str:
    """How many seats one user currently holds for one event (for the per-user cap)."""
    return f"uhold:{event_id}:{user_id}"


def idempotency_key(user_id: int, key: str) -> str:
    """The stored outcome of one user's request with one Idempotency-Key (24h)."""
    return f"idem:{user_id}:{key}"


def rehydrate_lock_key(event_id: int, tier_id: int) -> str:
    """Held by whichever process is rebuilding this tier's missing counter."""
    return f"lock:rehydrate:{event_id}:{tier_id}"
