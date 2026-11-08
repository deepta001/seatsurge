"""Redis key names match the schema in CLAUDE.md section 5."""

from app.redis.keys import HOLDS_EXPIRY_KEY, hold_key, inventory_key, user_hold_key


def test_key_names() -> None:
    assert inventory_key(42, 7) == "inv:42:7:avail"
    assert hold_key("abc") == "hold:abc"
    assert user_hold_key(42, 9) == "uhold:42:9"
    assert HOLDS_EXPIRY_KEY == "holds:expiry"
