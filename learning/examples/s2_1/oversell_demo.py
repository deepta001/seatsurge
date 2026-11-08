"""DELIBERATELY BROKEN: watch naive "check, then take" sell more seats than exist.

Many buyers start at the same instant. Each checks whether a seat is left,
then takes one, with a small wait in between (like a network round trip).
While one buyer waits, others check the same old count and also see a seat.

This file is a lesson, never app code (CLAUDE.md S2.1). Run from the project root:

    uv run python -m learning.examples.s2_1.oversell_demo
    uv run python -m learning.examples.s2_1.oversell_demo --mode redis --buyers 1000 --seats 100
"""

import argparse
import asyncio
import random
from dataclasses import dataclass

from redis.asyncio import BlockingConnectionPool, Redis

from app.core.settings import get_settings

DEMO_KEY = "demo:s2_1:available"  # a throwaway key, deleted at the end


def demo_redis_client() -> Redis:
    # A blocking pool of 50 connections: when all are busy, a request WAITS
    # for one, like on a real server. (The default pool raises
    # MaxConnectionsError when 1,000 requests arrive at once; found here.)
    pool = BlockingConnectionPool.from_url(
        get_settings().redis_url.get_secret_value(), max_connections=50, decode_responses=True
    )
    return Redis(connection_pool=pool)


@dataclass
class Result:
    sold: int  # how many buyers were told "you got a seat"
    counter_after: int  # what the seat counter says at the end


async def run_in_memory(seats: int, buyers: int) -> Result:
    available = seats
    sold = 0
    start = asyncio.Event()

    async def buy() -> None:
        nonlocal available, sold
        await start.wait()  # everyone lines up, then all go at once
        if available > 0:  # 1. CHECK
            # The gap: a real server would be waiting on the network or a
            # database here. Other buyers run during this pause.
            await asyncio.sleep(random.uniform(0, 0.002))
            available -= 1  # 2. TAKE, based on a check that may be stale now
            sold += 1

    tasks = [asyncio.create_task(buy()) for _ in range(buyers)]
    await asyncio.sleep(0)  # let every task reach the start line
    start.set()
    await asyncio.gather(*tasks)
    return Result(sold=sold, counter_after=available)


async def run_against_redis(seats: int, buyers: int) -> Result:
    redis = demo_redis_client()
    await redis.set(DEMO_KEY, seats)
    sold = 0
    start = asyncio.Event()

    async def buy() -> None:
        nonlocal sold
        await start.wait()
        available = int(await redis.get(DEMO_KEY) or 0)  # 1. CHECK (one network trip)
        if available > 0:
            await redis.decr(DEMO_KEY)  # 2. TAKE (another trip, the check may be stale)
            sold += 1

    try:
        tasks = [asyncio.create_task(buy()) for _ in range(buyers)]
        await asyncio.sleep(0)
        start.set()
        await asyncio.gather(*tasks)
        counter_after = int(await redis.get(DEMO_KEY) or 0)
    finally:
        await redis.delete(DEMO_KEY)
        await redis.aclose()
        await redis.connection_pool.disconnect()
    return Result(sold=sold, counter_after=counter_after)


def report(label: str, seats: int, result: Result) -> None:
    oversold = max(0, result.sold - seats)
    verdict = "OVERSOLD!" if oversold else "ok (got lucky)"
    print(
        f"{label:<8} seats={seats:<4} sold={result.sold:<5} oversold={oversold:<5} "
        f"counter_after={result.counter_after:<5} {verdict}"
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description="Watch check-then-take oversell.")
    parser.add_argument("--mode", choices=["memory", "redis", "both"], default="both")
    parser.add_argument("--seats", type=int, default=100)
    parser.add_argument("--buyers", type=int, default=1000)
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()

    for run in range(1, args.runs + 1):
        print(f"--- run {run} ({args.buyers} buyers, 1 seat each) ---")
        if args.mode in ("memory", "both"):
            report("memory", args.seats, await run_in_memory(args.seats, args.buyers))
        if args.mode in ("redis", "both"):
            report("redis", args.seats, await run_against_redis(args.seats, args.buyers))


if __name__ == "__main__":
    asyncio.run(main())
