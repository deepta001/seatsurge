"""Uses the seat counter from seats.py, to show how one module imports another (S0.3)."""

from seats import Tier, summary


def main() -> None:
    tiers: dict[str, Tier] = {
        "floor": Tier("floor", capacity=3),
        "balcony": Tier("balcony", capacity=5),
    }
    print("start:", summary(tiers))
    print("sell 2 floor ->", tiers["floor"].sell(2))
    print("sell 2 floor ->", tiers["floor"].sell(2))  # only 1 left, so this is refused
    print("sell 5 balcony ->", tiers["balcony"].sell(5))
    print("end:  ", summary(tiers))


# Only runs when you start this file directly, not when another file imports it.
if __name__ == "__main__":
    main()
