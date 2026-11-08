"""Password hashing with argon2: store a one-way hash, never the password itself.

A hash can check a password but can't be turned back into one, so a leaked
database doesn't hand out everyone's passwords.
"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

# argon2's defaults follow current security guidance: deliberately slow and
# memory-hungry, so guessing billions of passwords is impractical.
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Return an argon2 hash. Each call uses a fresh random salt, so equal passwords differ."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """True only if `password` is the one that produced `password_hash`."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False
