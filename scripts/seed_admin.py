"""Create an ADMIN account. This is the only way admins are made (CLAUDE.md section 9).

Run from the project root with Docker up and migrations applied:

    uv run python -m scripts.seed_admin --email you@example.com --username you

It asks for the password twice (nothing is shown as you type). For scripts
and CI, set SEATSURGE_ADMIN_PASSWORD instead. There is no default password.
"""

import argparse
import asyncio
import getpass
import os
import sys

from app.core.errors import UserAlreadyExists
from app.db.session import create_db_engine, create_session_factory
from app.services.auth import create_admin

MIN_PASSWORD_LENGTH = 12  # the same rule as self-registration


def read_password() -> str:
    from_env = os.environ.get("SEATSURGE_ADMIN_PASSWORD")
    if from_env:
        return from_env
    first = getpass.getpass("Admin password: ")
    second = getpass.getpass("Repeat password: ")
    if first != second:
        sys.exit("Passwords don't match.")
    return first


async def seed(email: str, username: str, password: str) -> int:
    engine = create_db_engine()
    try:
        async with create_session_factory(engine)() as session:
            user = await create_admin(session, email=email, username=username, password=password)
        return user.id
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Create a seatsurge ADMIN account.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--username", required=True)
    args = parser.parse_args(argv)

    password = read_password()
    if len(password) < MIN_PASSWORD_LENGTH:
        sys.exit(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")

    try:
        user_id = asyncio.run(seed(args.email, args.username, password))
    except UserAlreadyExists:
        sys.exit("That email or username is already registered.")
    print(f"Created ADMIN '{args.username}' with id {user_id}.")


if __name__ == "__main__":
    main()
