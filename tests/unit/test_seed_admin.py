"""The admin CLI refuses weak or mistyped passwords before touching the database."""

import getpass

import pytest

from scripts import seed_admin

ARGS = ["--email", "boss@example.com", "--username", "boss"]


def test_a_short_password_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEATSURGE_ADMIN_PASSWORD", "short")

    with pytest.raises(SystemExit) as exit_info:
        seed_admin.main(ARGS)

    assert "at least 12" in str(exit_info.value)


def test_mismatched_passwords_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEATSURGE_ADMIN_PASSWORD", raising=False)
    typed = iter(["first long password", "second long password"])
    monkeypatch.setattr(getpass, "getpass", lambda prompt: next(typed))

    with pytest.raises(SystemExit) as exit_info:
        seed_admin.main(ARGS)

    assert "don't match" in str(exit_info.value)


def test_email_and_username_are_required() -> None:
    with pytest.raises(SystemExit):
        seed_admin.main([])
