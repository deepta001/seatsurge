"""The worker process: background jobs that run beside the API (CLAUDE.md section 3).

For now it runs only the hold sweeper. The outbox relay and the stream
consumer join it in Phase C. Run from the project root:

    uv run python -m app.worker.main
"""

import asyncio
import logging

from app.redis.client import create_redis_client
from app.worker.sweeper import run_sweeper


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    redis = create_redis_client()
    try:
        await run_sweeper(redis)
    finally:
        await redis.aclose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass  # Ctrl+C: a normal way to stop it
