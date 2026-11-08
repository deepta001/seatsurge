"""Refresh tokens: random, single-use, stored only as a hash, and replaced on every use.

Every token descended from one login shares a family. Presenting an already
used token means two parties hold copies (one probably stolen), so the whole
family is revoked and both must log in again.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotAuthenticated
from app.core.settings import get_settings
from app.db.models import RefreshToken, User


@dataclass(frozen=True)
class Rotation:
    """The result of a successful refresh: who it was for, and their replacement token."""

    user: User
    refresh_token: str


def hash_refresh_token(raw_token: str) -> str:
    # Fast SHA-256 is right here, unlike for passwords: the token is 256 random
    # bits, so there's nothing for an attacker to guess even with a fast hash.
    return hashlib.sha256(raw_token.encode()).hexdigest()


def _add_token(session: AsyncSession, user_id: int, family_id: uuid.UUID, now: datetime) -> str:
    """Stage a new token row (caller commits) and return the raw token for the client."""
    raw_token = secrets.token_urlsafe(32)  # 256 bits from the OS's secure random source
    session.add(
        RefreshToken(
            user_id=user_id,
            token_hash=hash_refresh_token(raw_token),
            family_id=family_id,
            expires_at=now + timedelta(days=get_settings().refresh_token_days),
        )
    )
    return raw_token


async def issue_refresh_token(
    session: AsyncSession, user_id: int, now: datetime | None = None
) -> str:
    """Start a new family at login and return its first token."""
    raw_token = _add_token(session, user_id, uuid.uuid4(), now or datetime.now(UTC))
    await session.commit()
    return raw_token


async def rotate_refresh_token(
    session: AsyncSession, raw_token: str, now: datetime | None = None
) -> Rotation:
    """Spend a refresh token and return its replacement. Raises NotAuthenticated if invalid."""
    now = now or datetime.now(UTC)
    token_hash = hash_refresh_token(raw_token)

    # Claim the token in ONE statement: it's marked used only if it is still
    # unused, unrevoked and unexpired. If two requests race with the same token,
    # Postgres lets exactly one UPDATE match; the other finds it already used.
    claim = update(RefreshToken).where(
        RefreshToken.token_hash == token_hash,
        RefreshToken.used_at.is_(None),
        RefreshToken.revoked_at.is_(None),
        RefreshToken.expires_at > now,
    )
    claimed = (
        await session.execute(
            claim.values(used_at=now)
            .returning(RefreshToken.user_id, RefreshToken.family_id)
            .execution_options(synchronize_session=False)
        )
    ).one_or_none()

    if claimed is None:
        await _revoke_family_if_reused(session, token_hash, now)
        raise NotAuthenticated()

    # Read the user fresh, so a role change takes effect at the next refresh.
    user = await session.get(User, claimed.user_id)
    if user is None:  # unreachable while tokens cascade-delete with their user
        raise NotAuthenticated()
    new_token = _add_token(session, user.id, claimed.family_id, now)
    await session.commit()
    return Rotation(user=user, refresh_token=new_token)


async def revoke_refresh_token_family(
    session: AsyncSession, raw_token: str, now: datetime | None = None
) -> None:
    """Logout: revoke every token from the same login. Unknown tokens are ignored."""
    family_id = await session.scalar(
        select(RefreshToken.family_id).where(
            RefreshToken.token_hash == hash_refresh_token(raw_token)
        )
    )
    if family_id is not None:
        await _revoke_family(session, family_id, now or datetime.now(UTC))
    await session.commit()


async def _revoke_family_if_reused(session: AsyncSession, token_hash: str, now: datetime) -> None:
    """A rejected token that was already USED means a copy exists elsewhere: revoke its family."""
    used_token = await session.scalar(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash, RefreshToken.used_at.is_not(None)
        )
    )
    if used_token is not None:
        await _revoke_family(session, used_token.family_id, now)
    await session.commit()


async def _revoke_family(session: AsyncSession, family_id: uuid.UUID, now: datetime) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
        .execution_options(synchronize_session=False)
    )
