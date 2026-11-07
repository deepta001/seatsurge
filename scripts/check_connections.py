"""Checks that the app can reach Postgres and Redis using the settings in .env.

Run from the project root: uv run python -m scripts.check_connections
"""

import asyncio

from sqlalchemy import text

from app.db.session import create_db_engine
from app.redis.client import create_redis_client


async def check_postgres() -> None:
    engine = create_db_engine()
    try:
        async with engine.connect() as connection:
            version = await connection.scalar(text("SHOW server_version"))
            print(f"Postgres OK: server version {version}")
    finally:
        # Close the pooled connections so the script exits cleanly.
        await engine.dispose()


async def check_redis() -> None:
    redis = create_redis_client()
    try:
        await redis.ping()
        info = await redis.info("server")
        # A key with a 10-second TTL: it deletes itself, so nothing is left behind.
        await redis.set("check:hello", "world", ex=10)
        value = await redis.get("check:hello")
        print(f"Redis OK: server version {info['redis_version']}, read back {value!r}")
    finally:
        await redis.aclose()


async def main() -> None:
    await check_postgres()
    await check_redis()


if __name__ == "__main__":
    asyncio.run(main())
