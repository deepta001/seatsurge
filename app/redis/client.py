"""Creates the async Redis client the app uses to talk to Redis (the fast gate)."""

from redis.asyncio import Redis

from app.core.settings import get_settings


def create_redis_client() -> Redis:
    """Build a client from REDIS_URL. It keeps its own connection pool, so create it once."""
    settings = get_settings()
    return Redis.from_url(
        settings.redis_url.get_secret_value(),
        # Return str instead of bytes, so b"5" comes back as "5".
        decode_responses=True,
    )
