"""Tests for signing and checking access tokens (app/core/tokens.py)."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.errors import NotAuthenticated
from app.core.settings import get_settings
from app.core.tokens import create_access_token, decode_access_token
from app.db.models import UserRole

SECRET = get_settings().jwt_secret_key.get_secret_value()


def test_a_fresh_token_decodes_to_the_same_user_and_role() -> None:
    token = create_access_token(7, UserRole.ADMIN)

    claims = decode_access_token(token)

    assert claims.user_id == 7
    assert claims.role == UserRole.ADMIN


def test_the_token_expires_after_15_minutes() -> None:
    issued = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    payload = jwt.decode(
        create_access_token(7, UserRole.USER, now=issued),
        SECRET,
        algorithms=["HS256"],
        options={"verify_exp": False},
    )
    assert payload["exp"] - payload["iat"] == 15 * 60


def test_an_expired_token_is_rejected() -> None:
    sixteen_minutes_ago = datetime.now(UTC) - timedelta(minutes=16)
    token = create_access_token(7, UserRole.USER, now=sixteen_minutes_ago)

    with pytest.raises(NotAuthenticated):
        decode_access_token(token)


def test_changing_the_payload_breaks_the_signature() -> None:
    # Promote yourself to ADMIN by editing the token's middle part...
    header, _payload, signature = create_access_token(7, UserRole.USER).split(".")
    forged_payload = jwt.encode(
        {"sub": "7", "role": "ADMIN", "type": "access", "iat": 0, "exp": 9999999999},
        "attacker-does-not-know-the-real-key-000000",
        algorithm="HS256",
    ).split(".")[1]
    forged = f"{header}.{forged_payload}.{signature}"

    # ...and the old signature no longer matches, so it's rejected.
    with pytest.raises(NotAuthenticated):
        decode_access_token(forged)


def test_a_token_signed_with_another_key_is_rejected() -> None:
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": "7",
            "role": "ADMIN",
            "type": "access",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        "some-other-key-that-is-also-32-characters-long",
        algorithm="HS256",
    )
    with pytest.raises(NotAuthenticated):
        decode_access_token(token)


def test_an_unsigned_alg_none_token_is_rejected() -> None:
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": "7",
            "role": "ADMIN",
            "type": "access",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        key=None,
        algorithm="none",
    )
    with pytest.raises(NotAuthenticated):
        decode_access_token(token)


def test_a_non_access_token_is_rejected() -> None:
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": "7",
            "role": "USER",
            "type": "refresh",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        SECRET,
        algorithm="HS256",
    )
    with pytest.raises(NotAuthenticated):
        decode_access_token(token)


def test_junk_is_rejected() -> None:
    with pytest.raises(NotAuthenticated):
        decode_access_token("not.a.token")
