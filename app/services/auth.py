"""Account business logic: registering users and checking login credentials.

Kept apart from HTTP, so it can be called and tested without a web request.
"""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import InvalidCredentials, UserAlreadyExists
from app.core.security import hash_password, verify_password
from app.db.models import User, UserRole

# A real argon2 hash of a password nobody uses. When the email is unknown we
# still check against this, so "no such user" takes as long as "wrong password"
# and response timing can't reveal which emails are registered.
_DUMMY_PASSWORD_HASH = hash_password("timing-equaliser-not-a-real-password")


async def authenticate_user(session: AsyncSession, *, email: str, password: str) -> User:
    """Return the user if the email and password match. Otherwise raise InvalidCredentials."""
    user = await session.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None:
        verify_password(password, _DUMMY_PASSWORD_HASH)  # spend the same time anyway
        raise InvalidCredentials()
    if not verify_password(password, user.password_hash):
        raise InvalidCredentials()
    return user


async def register_user(session: AsyncSession, *, email: str, username: str, password: str) -> User:
    """Create a new account and return it. Raises UserAlreadyExists on a duplicate.

    There is deliberately no `role` parameter: self-registration can only ever
    create a USER (CLAUDE.md section 9). Admins come from a separate CLI (S1.6).
    """
    user = User(
        # Lower-case, so "Asha@Example.com" and "asha@example.com" count as one email.
        email=email.strip().lower(),
        username=username.strip(),
        password_hash=hash_password(password),
        role=UserRole.USER,
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as error:
        # No "check first, then insert": two sign-ups for the same email at the
        # same moment could both pass the check. The UNIQUE constraint decides
        # atomically, and we turn its refusal into a typed error.
        await session.rollback()
        if violated_constraint(error) in DUPLICATE_ACCOUNT_CONSTRAINTS:
            raise UserAlreadyExists() from error
        # Any other integrity failure is a bug, not a duplicate; let it surface.
        raise
    return user


DUPLICATE_ACCOUNT_CONSTRAINTS = {"uq_users_email", "uq_users_username"}


def violated_constraint(error: IntegrityError) -> str | None:
    """The name of the database constraint that rejected the write, if known."""
    # SQLAlchemy wraps the asyncpg error; asyncpg reports the constraint name.
    driver_error = getattr(error.orig, "__cause__", None)
    name = getattr(driver_error, "constraint_name", None)
    return name if isinstance(name, str) else None
