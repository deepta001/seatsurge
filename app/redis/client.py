"""Creates the async Redis client the app uses to talk to Redis (the fast gate)."""

from redis.asyncio import BlockingConnectionPool, Redis

from app.core.settings import get_settings


def create_redis_client() -> Redis:
    """The app's Redis client, configured from settings. Create it once per process."""
    settings = get_settings()
    return build_redis_client(
        settings.redis_url.get_secret_value(),
        max_connections=settings.redis_max_connections,
        pool_timeout_seconds=settings.redis_pool_timeout_seconds,
    )


def build_redis_client(url: str, *, max_connections: int, pool_timeout_seconds: float) -> Redis:
    """A Redis client with a bounded, *waiting* connection pool.

    When every connection is busy, a request waits up to `pool_timeout_seconds`
    for one instead of failing at once. In S2.1 the default pool raised
    MaxConnectionsError when 1,000 requests arrived together, which is exactly
    what a ticket sale looks like.
    """
    pool = BlockingConnectionPool.from_url(
        url,
        max_connections=max_connections,
        timeout=pool_timeout_seconds,
        # Return str instead of bytes, so b"5" comes back as "5".
        decode_responses=True,
    )
    # from_pool makes the client own the pool, so `await client.aclose()`
    # (in app shutdown) also closes every pooled connection.
    return Redis.from_pool(pool)
