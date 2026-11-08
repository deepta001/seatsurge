"""Tests for password hashing in app/core/security.py."""

from app.core.security import hash_password, verify_password

PASSWORD = "correct horse battery staple"


def test_the_hash_does_not_contain_the_password() -> None:
    password_hash = hash_password(PASSWORD)

    assert PASSWORD not in password_hash
    assert password_hash.startswith("$argon2id$")


def test_the_right_password_verifies() -> None:
    assert verify_password(PASSWORD, hash_password(PASSWORD)) is True


def test_a_wrong_password_does_not_verify() -> None:
    assert verify_password("wrong password", hash_password(PASSWORD)) is False


def test_the_same_password_hashes_differently_each_time() -> None:
    # A random salt per hash means two users with the same password get
    # different hashes, so one cracked hash doesn't reveal the other.
    assert hash_password(PASSWORD) != hash_password(PASSWORD)


def test_a_garbage_hash_is_a_failed_check_not_a_crash() -> None:
    assert verify_password(PASSWORD, "not-a-hash") is False
