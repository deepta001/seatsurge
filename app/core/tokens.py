"""Creates and checks signed access tokens (JWTs).

A token is a small JSON payload ("user 7, role USER, expires 16:05") plus a
signature made with JWT_SECRET_KEY. Anyone can read the payload, but nobody
without the key can change it or make a new one, so the API can trust it
without asking the database.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from app.core.errors import NotAuthenticated
from app.core.settings import get_settings
from app.db.models import UserRole

# Pin the one algorithm we sign with. Accepting whatever the token's header
# claims would let an attacker pick "none" (no signature at all).
ALGORITHM = "HS256"
ACCESS_TOKEN_TYPE = "access"


@dataclass(frozen=True)
class AccessTokenClaims:
    """What a verified access token tells us: who the caller is and their role."""

    user_id: int
    role: UserRole


def create_access_token(user_id: int, role: UserRole, now: datetime | None = None) -> str:
    """Sign a token for this user that expires after `access_token_minutes`."""
    settings = get_settings()
    issued_at = now or datetime.now(UTC)
    payload = {
        "sub": str(user_id),  # "subject": who the token is about (a string by convention)
        "role": role.value,
        "type": ACCESS_TOKEN_TYPE,  # so a refresh token (S1.5) can't be used as one
        "iat": issued_at,
        "exp": issued_at + timedelta(minutes=settings.access_token_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key.get_secret_value(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> AccessTokenClaims:
    """Verify the signature and expiry and return the claims, or raise NotAuthenticated."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[ALGORITHM],
            options={"require": ["sub", "role", "type", "exp", "iat"]},
        )
        if payload["type"] != ACCESS_TOKEN_TYPE:
            raise NotAuthenticated()
        return AccessTokenClaims(user_id=int(payload["sub"]), role=UserRole(payload["role"]))
    # Expired, tampered, wrong key, missing claims, or junk: all the same to the
    # caller. The reason isn't revealed (CLAUDE.md rule 10).
    except (jwt.InvalidTokenError, ValueError, KeyError) as error:
        raise NotAuthenticated() from error
