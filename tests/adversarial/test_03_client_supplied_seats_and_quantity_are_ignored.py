"""Adversarial test 3: seat ids, quantities or prices sent at confirm time change nothing.

CLAUDE.md rule 1: confirm takes only a hold id (plus the payment token). The
quantity comes from the server-side hold and the price from the database.
Extra fields are refused outright (422), so they can't be "half-used" either.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.services.payments import MockPaymentProvider
from tests.sales import Sale, confirm, hold


@pytest.mark.parametrize(
    "tampering",
    [
        {"quantity": 100},
        {"seat_ids": [1, 2, 3, 4, 5]},
        {"total_cents": 1},
        {"tier_id": 999},
        {"user_id": 1},
    ],
)
async def test_extra_fields_at_confirm_are_refused_and_nothing_is_bought(
    client: AsyncClient,
    db_engine: AsyncEngine,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
    tampering: dict[str, object],
) -> None:
    hold_id = (await hold(client, sale, user_id=buyers[0], quantity=2)).json()["hold_id"]

    response = await confirm(client, hold_id, buyers[0], extra=tampering)

    assert response.status_code == 422
    async with db_engine.connect() as connection:
        assert await connection.scalar(text("SELECT count(*) FROM orders")) == 0
    assert payments._charges_by_key == {}


async def test_the_order_uses_the_holds_quantity_and_the_databases_price(
    client: AsyncClient,
    db_engine: AsyncEngine,
    sale: Sale,
    buyers: list[int],
    payments: MockPaymentProvider,
) -> None:
    hold_id = (await hold(client, sale, user_id=buyers[0], quantity=2)).json()["hold_id"]

    response = await confirm(client, hold_id, buyers[0])

    assert response.status_code == 202
    async with db_engine.connect() as connection:
        order = (
            await connection.execute(text("SELECT quantity, total_cents, tier_id FROM orders"))
        ).one()
    assert (order.quantity, order.total_cents, order.tier_id) == (2, 2 * 5000, sale.tier_id)
    [charge] = payments._charges_by_key.values()
    assert charge.amount_cents == 2 * 5000
