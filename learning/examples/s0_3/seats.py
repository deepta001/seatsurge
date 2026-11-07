"""A tiny in-memory seat counter for practising type hints, classes and modules (S0.3).

This is a learning toy, not project code: it has no locking, so it is NOT safe
when many users buy at once. Phase B shows why.
"""


class Tier:
    """One price level of an event, for example 'floor' with 3 seats."""

    def __init__(self, name: str, capacity: int) -> None:
        self.name = name
        self.capacity = capacity
        self.sold = 0

    def available(self) -> int:
        """How many seats are still unsold."""
        return self.capacity - self.sold

    def sell(self, quantity: int) -> bool:
        """Sell `quantity` seats if there are enough. Returns True on success."""
        if quantity <= 0:
            return False
        if quantity > self.available():
            # Early return: refuse the whole request and change nothing,
            # rather than selling only part of it.
            return False
        self.sold += quantity
        return True


def summary(tiers: dict[str, Tier]) -> dict[str, int]:
    """Map each tier name to how many seats it has left."""
    result: dict[str, int] = {}
    for name, tier in tiers.items():
        result[name] = tier.available()
    return result
