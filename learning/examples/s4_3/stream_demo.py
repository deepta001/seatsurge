"""Shows a Redis Stream with a consumer group: two workers share entries; one isn't acked.

Uses its own stream (`demo:s4_3:stream`), never `stream:orders`, and deletes
only that key at the end. Run from the project root:

    uv run python -m learning.examples.s4_3.stream_demo
"""

import asyncio

from app.redis.client import create_redis_client

STREAM = "demo:s4_3:stream"
GROUP = "demo-workers"


async def main() -> None:
    redis = create_redis_client()
    try:
        for n in range(1, 5):
            entry_id = await redis.xadd(STREAM, {"order": f"order-{n}"})
            print(f"XADD order-{n} -> {entry_id}")

        # Created AFTER the entries exist: id "0" still delivers all of them.
        await redis.xgroup_create(STREAM, GROUP, id="0", mkstream=True)

        for worker in ("worker-a", "worker-b"):
            response = await redis.xreadgroup(GROUP, worker, {STREAM: ">"}, count=2)
            got = [
                (entry_id, fields["order"])
                for _, entries in response
                for entry_id, fields in entries
            ]
            print(f"{worker} was given {[order for _, order in got]}")
            for entry_id, order in got:
                if order == "order-4":
                    print(f"{worker} 'crashes' while handling {order}: no XACK")
                    continue
                await redis.xack(STREAM, GROUP, entry_id)

        nothing_new = await redis.xreadgroup(GROUP, "worker-a", {STREAM: ">"}, count=10)
        print(f"asking for new entries again gives: {nothing_new}")
        summary = await redis.xpending(STREAM, GROUP)
        print(f"pending (given out, never acked): {summary['pending']} -> {summary['consumers']}")
    finally:
        await redis.delete(STREAM)
        print(f"deleted {STREAM}")
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
