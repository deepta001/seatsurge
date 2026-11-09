"""The headline load test (CLAUDE.md section 1): many buyers, few seats, through nginx (S8.3).

Each simulated user is one real buyer who tries ONCE: hold 1 seat; if that
worked, confirm it (mock payment); then stop. A 409 sold_out is the
expected answer for most of them, so it counts as a success, not an error.
When every user has finished, the test stops by itself.

    uv run python -m loadtest.prepare --seats 100 --users 1000
    uv run --group load python -m locust -f loadtest/locustfile.py --headless \\
        -u 1000 -r 1000 --run-time 3m --host http://127.0.0.1:8080 --csv loadtest/results/run
    uv run python -m scripts.verify_consistency --wait 60
    uv run python -m loadtest.cleanup

Tokens are signed here with the app's JWT secret (from .env) instead of
logging in 1,000 times: login is rate limited per IP (20 a minute), and the
sale, not the login, is what this test measures.
"""

import json
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from locust import FastHttpUser, constant, events, task
from locust.exception import StopUser

from app.core.tokens import create_access_token
from app.db.models import UserRole

RUN_FILE = Path(__file__).parent / "run.json"
CREATED_FILE = Path(__file__).parent / "created.json"

RUN: dict[str, Any] = json.loads(RUN_FILE.read_text(encoding="utf-8"))
UNUSED_BUYERS = iter(RUN["user_ids"])
OUTCOMES: Counter[str] = Counter()
# What this run created in Redis, so cleanup can delete exactly that.
CREATED: dict[str, list[Any]] = {"hold_ids": [], "idempotency_keys": []}


class Buyer(FastHttpUser):
    wait_time = constant(0)  # no "thinking time": everyone clicks at once

    def on_start(self) -> None:
        self.user_id = next(UNUSED_BUYERS)
        self.headers = {
            "Authorization": f"Bearer {create_access_token(self.user_id, UserRole.USER)}"
        }

    def new_key(self) -> str:
        key = str(uuid.uuid4())
        CREATED["idempotency_keys"].append([self.user_id, key])
        return key

    @task
    def buy_one_ticket(self) -> None:
        try:
            self.try_to_buy()
        finally:
            self.finish()

    def try_to_buy(self) -> None:
        with self.client.post(
            f"/events/{RUN['event_id']}/holds",
            json={"tier_id": RUN["tier_id"], "quantity": 1},
            headers={**self.headers, "Idempotency-Key": self.new_key()},
            name="POST /events/[id]/holds",
            catch_response=True,
        ) as held:
            if held.status_code == 409:
                held.success()  # sold out: the expected answer for most buyers
                OUTCOMES["hold: sold out (409)"] += 1
                return
            if held.status_code != 201:
                held.failure(f"hold answered {held.status_code}")
                OUTCOMES[f"hold: unexpected {held.status_code}"] += 1
                return
            OUTCOMES["hold: got a seat (201)"] += 1
            hold_id = held.json()["hold_id"]
            CREATED["hold_ids"].append(hold_id)

        with self.client.post(
            f"/holds/{hold_id}/confirm",
            json={"payment_token": "tok_ok"},
            headers={**self.headers, "Idempotency-Key": self.new_key()},
            name="POST /holds/[id]/confirm",
            catch_response=True,
        ) as confirmed:
            if confirmed.status_code == 202:
                OUTCOMES["confirm: order accepted (202)"] += 1
            else:
                confirmed.failure(f"confirm answered {confirmed.status_code}")
                OUTCOMES[f"confirm: unexpected {confirmed.status_code}"] += 1

    def finish(self) -> None:
        """This buyer is done. The last one to finish ends the whole test."""
        OUTCOMES["buyers finished"] += 1
        if OUTCOMES["buyers finished"] == self.environment.parsed_options.num_users:
            self.environment.runner.quit()
        raise StopUser()


def report(environment: Any, **_kwargs: Any) -> None:
    """Print what happened and save what was created (for loadtest/cleanup.py)."""
    CREATED_FILE.write_text(json.dumps(CREATED), encoding="utf-8")
    print("\nOutcomes:")
    for outcome, count in sorted(OUTCOMES.items()):
        print(f"  {outcome:32} {count}")


# Runs once when Locust stops (after the last buyer, or at --run-time).
events.quitting.add_listener(report)  # type: ignore[no-untyped-call]  # locust lacks a hint
