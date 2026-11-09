"""The mock payment provider behaves like a real one: tokens, declines, idempotency, refunds."""

import random

import pytest
from fastapi.testclient import TestClient

from app.core.errors import InvalidPaymentToken, PaymentDeclined, PaymentUnavailable
from app.main import app
from app.services.payments import (
    TOKEN_DECLINED,
    TOKEN_OK,
    TOKEN_UNAVAILABLE,
    MockPaymentProvider,
)


async def test_a_good_token_is_charged() -> None:
    charge = await MockPaymentProvider().charge(
        token=TOKEN_OK, amount_cents=4500, idempotency_key="k1"
    )

    assert charge.amount_cents == 4500
    assert charge.charge_id.startswith("ch_")


@pytest.mark.parametrize(
    ("token", "error"),
    [
        (TOKEN_DECLINED, PaymentDeclined),
        (TOKEN_UNAVAILABLE, PaymentUnavailable),
        ("4242424242424242", InvalidPaymentToken),  # a raw card number is never accepted
        ("", InvalidPaymentToken),
    ],
)
async def test_bad_tokens_raise_typed_errors(token: str, error: type[Exception]) -> None:
    with pytest.raises(error):
        await MockPaymentProvider().charge(token=token, amount_cents=100, idempotency_key="k")


async def test_retrying_a_charge_with_the_same_key_charges_once() -> None:
    provider = MockPaymentProvider()

    first = await provider.charge(token=TOKEN_OK, amount_cents=4500, idempotency_key="same")
    retry = await provider.charge(token=TOKEN_OK, amount_cents=4500, idempotency_key="same")

    assert retry == first


async def test_the_same_key_for_a_different_amount_is_refused() -> None:
    provider = MockPaymentProvider()
    await provider.charge(token=TOKEN_OK, amount_cents=4500, idempotency_key="same")

    with pytest.raises(ValueError):
        await provider.charge(token=TOKEN_OK, amount_cents=9999, idempotency_key="same")


async def test_failure_rate_zero_never_declines_and_one_always_does() -> None:
    never = MockPaymentProvider(failure_rate=0.0)
    always = MockPaymentProvider(failure_rate=1.0)

    for n in range(100):
        await never.charge(token=TOKEN_OK, amount_cents=1, idempotency_key=f"n{n}")
    with pytest.raises(PaymentDeclined):
        await always.charge(token=TOKEN_OK, amount_cents=1, idempotency_key="a")


async def test_a_seeded_failure_rate_is_repeatable_and_roughly_right() -> None:
    async def declines(seed: int) -> int:
        provider = MockPaymentProvider(failure_rate=0.3, rng=random.Random(seed))
        declined = 0
        for n in range(1000):
            try:
                await provider.charge(token=TOKEN_OK, amount_cents=1, idempotency_key=f"k{n}")
            except PaymentDeclined:
                declined += 1
        return declined

    first, again = await declines(seed=7), await declines(seed=7)

    assert first == again  # same seed, same "random" declines
    assert 250 <= first <= 350  # about 30% of 1,000


async def test_refunds_are_recorded_and_safe_to_repeat() -> None:
    provider = MockPaymentProvider()
    charge = await provider.charge(token=TOKEN_OK, amount_cents=100, idempotency_key="k")

    await provider.refund(charge.charge_id)
    await provider.refund(charge.charge_id)

    assert provider.refunded == {charge.charge_id}


def test_an_invalid_failure_rate_is_rejected() -> None:
    with pytest.raises(ValueError):
        MockPaymentProvider(failure_rate=1.5)


def test_the_app_creates_one_provider_at_startup_and_exposes_no_payment_route() -> None:
    with TestClient(app) as client:
        assert isinstance(app.state.payments, MockPaymentProvider)
        # CLAUDE.md section 9: no test/simulation endpoints in the application.
        # The OpenAPI schema is the public list of routes (what /docs shows).
        paths = set(app.openapi()["paths"])
        assert "/events/{event_id}/holds" in paths  # sanity: the list is real
        assert not any("pay" in path for path in paths)
        assert client.post("/payments", json={}).status_code == 404
