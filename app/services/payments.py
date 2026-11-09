"""A mock payment provider: stands in for a real one (like Stripe) without any real money.

How real card payments work, and how this copies it:
  1. The client gets a payment TOKEN from the provider directly (our API never
     sees card numbers). In test mode, providers publish fixed test tokens.
  2. Our server asks the provider to CHARGE that token for an amount.
  3. If our own work then fails, our server asks for a REFUND.

This class plays the provider, in-process. There is deliberately no HTTP
endpoint for it: CLAUDE.md section 9 forbids test/simulation endpoints.

Test tokens:
  tok_ok          succeeds (unless randomly declined by `failure_rate`)
  tok_declined    always declined          -> PaymentDeclined (402)
  tok_unavailable provider "down"          -> PaymentUnavailable (503, retry)
  anything else   not a valid token        -> InvalidPaymentToken (422)
"""

import random
import uuid
from dataclasses import dataclass

from app.core.errors import InvalidPaymentToken, PaymentDeclined, PaymentUnavailable

TOKEN_OK = "tok_ok"
TOKEN_DECLINED = "tok_declined"
TOKEN_UNAVAILABLE = "tok_unavailable"


@dataclass(frozen=True)
class Charge:
    charge_id: str
    amount_cents: int


class MockPaymentProvider:
    """In-memory fake provider. One instance per process (created at startup)."""

    def __init__(self, failure_rate: float = 0.0, rng: random.Random | None = None) -> None:
        if not 0.0 <= failure_rate <= 1.0:
            raise ValueError("failure_rate must be between 0 and 1")
        self.failure_rate = failure_rate
        # A seeded Random makes "random" declines repeatable in tests.
        self._rng = rng or random.Random()
        # Like real providers, a charge is idempotent per key: a retried charge
        # returns the first result instead of charging the customer twice.
        self._charges_by_key: dict[str, Charge] = {}
        self.refunded: set[str] = set()

    async def charge(self, *, token: str, amount_cents: int, idempotency_key: str) -> Charge:
        """Charge the token, or raise PaymentDeclined / PaymentUnavailable / InvalidPaymentToken."""
        if amount_cents < 0:
            raise ValueError("amount_cents must not be negative")
        earlier = self._charges_by_key.get(idempotency_key)
        if earlier is not None:
            if earlier.amount_cents != amount_cents:
                # Same key, different amount: a client bug, as real providers say too.
                raise ValueError("idempotency key reused for a different amount")
            return earlier

        if token == TOKEN_UNAVAILABLE:
            raise PaymentUnavailable()
        if token == TOKEN_DECLINED:
            raise PaymentDeclined()
        if token != TOKEN_OK:
            raise InvalidPaymentToken()
        if self._rng.random() < self.failure_rate:
            raise PaymentDeclined()

        charge = Charge(charge_id=f"ch_{uuid.uuid4().hex}", amount_cents=amount_cents)
        self._charges_by_key[idempotency_key] = charge
        return charge

    async def refund(self, charge_id: str) -> None:
        """Give the money back. Refunding twice is harmless."""
        self.refunded.add(charge_id)
