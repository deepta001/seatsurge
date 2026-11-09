"""Adversarial test 2: a forged or someone else's hold id at confirm time gets no order.

CLAUDE.md rule 1: "A forged or foreign hold id must fail." Both answers are
the same 404, so an attacker can't even learn whether a hold id exists.
"""

from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.redis.keys import hold_key
from app.services.payments import MockPaymentProvider
from tests.sales import Sale, confirm, hold


async def order_count(db_engine: AsyncEngine) -> int:
    async with db_engine.connect() as connection:
        return int(await connection.scalar(text("SELECT count(*) FROM orders")) or 0)


async def test_a_made_up_hold_id_gets_404_and_nothing_is_charged(
    client: AsyncClient,
    db_engine: AsyncEngine,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
) -> None:
    response = await confirm(client, "00000000-0000-0000-0000-000000000000", buyers[0])

    assert (response.status_code, response.json()["error"]) == (404, "hold_not_found")
    assert await order_count(db_engine) == 0
    assert payments._charges_by_key == {}


async def test_someone_elses_hold_gets_the_same_404_and_stays_theirs(
    client: AsyncClient,
    redis: Redis,
    db_engine: AsyncEngine,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
) -> None:
    alice, mallory = buyers[0], buyers[1]
    alices_hold = (await hold(client, sale, user_id=alice, quantity=4)).json()["hold_id"]

    stolen = await confirm(client, alices_hold, mallory)
    made_up = await confirm(client, "00000000-0000-0000-0000-000000000000", mallory)

    assert stolen.status_code == 404
    assert stolen.json() == made_up.json()  # indistinguishable from a made-up id
    assert await order_count(db_engine) == 0
    assert payments._charges_by_key == {}
    # Alice's hold is untouched and she can still buy it.
    assert await redis.hget(hold_key(alices_hold), "status") == "HELD"
    assert (await confirm(client, alices_hold, alice)).status_code == 202
