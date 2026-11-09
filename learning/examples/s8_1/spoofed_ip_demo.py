"""S8.1 demo: through nginx, a client can't fake its IP to dodge the per-IP login limit.

Each attempt uses a NEW email (so the per-email limit never triggers) and a
NEW made-up X-Forwarded-For header. If the API believed that header, every
attempt would look like a different IP and none would be limited. nginx
overwrites the header with the real address, so after the per-IP limit (20)
the API answers 429.

With the full stack up (docker compose up -d --build), from the project root:

    uv run python -m learning.examples.s8_1.spoofed_ip_demo

It deletes only the rate-limit keys it created.
"""

import asyncio
import uuid
from collections import Counter

import httpx

from app.redis.client import create_redis_client
from app.redis.rate_limit import hashed, rate_limit_key

NGINX = "http://127.0.0.1:8080"
ATTEMPTS = 25


async def main() -> None:
    emails = [f"spoof-{uuid.uuid4().hex[:8]}@example.com" for _ in range(ATTEMPTS)]
    statuses: Counter[int] = Counter()
    async with httpx.AsyncClient(base_url=NGINX) as http:
        for n, email in enumerate(emails, start=1):
            fake_ip = f"203.0.113.{n}"  # a different "IP" every time
            response = await http.post(
                "/auth/login",
                json={"email": email, "password": "not the password"},
                headers={"X-Forwarded-For": fake_ip},
            )
            statuses[response.status_code] += 1
    print(f"{ATTEMPTS} wrong logins, each with a new email and a new fake IP:")
    print(f"  answers: {dict(sorted(statuses.items()))}  (429 = limited by real IP)")

    # Clean up only this demo's keys. Through nginx the API sees the Docker
    # network's gateway as the client address.
    redis = create_redis_client()
    keys = [rate_limit_key("login-email", hashed(e)) for e in emails]
    keys += [rate_limit_key("login-ip", "172.28.5.1")]
    await redis.delete(*keys)
    await redis.aclose()
    print("cleaned up the demo's rate-limit keys")


if __name__ == "__main__":
    asyncio.run(main())
