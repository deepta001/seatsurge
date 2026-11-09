"""The worker process: background jobs that run beside the API (CLAUDE.md section 3).

It runs three asyncio tasks side by side: the hold sweeper, the outbox
relay, and the stream consumer that issues tickets. Run from the project root:

    uv run python -m app.worker.main
"""

import asyncio
import logging

from app.db.session import create_db_engine, create_session_factory
from app.redis.client import create_redis_client
from app.worker.consumer_loop import run_consumer
from app.worker.handlers import build_compensations, build_handlers
from app.worker.relay import run_relay
from app.worker.sweeper import run_sweeper


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    redis = create_redis_client()
    engine = create_db_engine()
    session_factory = create_session_factory(engine)
    try:
        # A TaskGroup runs the loops concurrently. Each loop catches its own
        # errors, so one failing pass never stops the other tasks.
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(run_sweeper(redis))
            tasks.create_task(run_relay(session_factory, redis))
            handlers = build_handlers(session_factory, redis)
            compensations = build_compensations(session_factory, redis)
            tasks.create_task(run_consumer(redis, handlers, compensations))
    finally:
        await engine.dispose()
        await redis.aclose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass  # Ctrl+C: a normal way to stop it
