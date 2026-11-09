"""S8.1 probe: how long do N simultaneous NEW connections take to get an answer?

Standard library only, so it can run on the host AND inside the Docker
network (the app image has no httpx), to tell apart the app, nginx and
Docker Desktop's port forwarding from Windows into the containers.

    uv run python -m learning.examples.s8_1.connection_probe 127.0.0.1 8080 1000

Inside Docker (the file is piped in, since the image doesn't contain learning/):

    docker compose run --rm --no-deps -T api sh -c \
        "cat > /tmp/p.py && python /tmp/p.py nginx 8080 1000" < connection_probe.py

In S8.1 this showed 1,000 new connections answered in ~1.5 s from Windows,
while an httpx client with a 1,000-connection pool took ~35 s for the same
requests: the slowness was the client, not the server.
"""

import asyncio
import sys
import time


async def one_request(host: str, port: int) -> float:
    started = time.perf_counter()
    reader, writer = await asyncio.open_connection(host, port)
    writer.write(f"GET /health/live HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode())
    await writer.drain()
    await reader.read()  # until the server closes
    writer.close()
    return time.perf_counter() - started


async def main(host: str, port: int, count: int) -> None:
    began = time.perf_counter()
    results = await asyncio.gather(
        *(one_request(host, port) for _ in range(count)), return_exceptions=True
    )
    times = sorted(r for r in results if isinstance(r, float))
    errors = len(results) - len(times)
    print(
        f"{count} new connections to {host}:{port}: wall {time.perf_counter() - began:.2f}s, "
        f"p50 {times[len(times) // 2]:.2f}s, slowest {times[-1]:.2f}s, errors {errors}"
    )


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], int(sys.argv[2]), int(sys.argv[3])))
