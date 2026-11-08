"""contains_pattern escapes LIKE wildcards so user text is matched literally."""

from app.services.events import contains_pattern


def test_plain_text_is_wrapped_for_contains() -> None:
    assert contains_pattern("jazz") == "%jazz%"


def test_percent_underscore_and_backslash_are_escaped() -> None:
    assert contains_pattern("50%") == "%50\\%%"
    assert contains_pattern("a_b") == "%a\\_b%"
    assert contains_pattern("c:\\x") == "%c:\\\\x%"
