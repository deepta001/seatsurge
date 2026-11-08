"""Account routes: register, login, refresh and logout under /auth."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session
from app.core.settings import get_settings
from app.core.tokens import create_access_token
from app.db.models import User, UserRole
from app.services.auth import authenticate_user, register_user
from app.services.refresh_tokens import (
    issue_refresh_token,
    revoke_refresh_token_family,
    rotate_refresh_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    # Reject unknown fields, so a sneaky {"role": "ADMIN"} gets a clear 422
    # instead of being silently ignored (test 15).
    model_config = ConfigDict(extra="forbid")

    # A light shape check (something@something.something). Proving an address
    # is real needs a confirmation email, which is out of scope.
    email: str = Field(max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_.-]+$")
    # The max length stops someone sending a 10 MB "password" to make hashing slow.
    password: str = Field(min_length=12, max_length=128)


class UserResponse(BaseModel):
    """What a client may see about a user: never the password hash."""

    id: int
    email: str
    username: str
    role: UserRole
    created_at: datetime


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest, session: AsyncSession = Depends(get_db_session)
) -> UserResponse:
    """Create an account. It is always a USER; there's no way to ask for more."""
    user = await register_user(
        session, email=body.email, username=body.username, password=body.password
    )
    return UserResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        role=user.role,
        created_at=user.created_at,
    )


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=320)
    # No minimum here: the password rules are checked at registration, and a
    # wrong password should just be "incorrect", not a hint about the rules.
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int  # seconds until the access token stops working
    # Single use: send it to POST /auth/refresh and you get a replacement.
    refresh_token: str
    refresh_expires_in: int  # seconds until the refresh token expires if unused


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(min_length=1, max_length=200)


def token_response(user: User, refresh_token: str) -> TokenResponse:
    settings = get_settings()
    return TokenResponse(
        access_token=create_access_token(user.id, user.role),
        expires_in=settings.access_token_minutes * 60,
        refresh_token=refresh_token,
        refresh_expires_in=settings.refresh_token_days * 24 * 60 * 60,
    )


@router.post("/login")
async def login(
    body: LoginRequest, session: AsyncSession = Depends(get_db_session)
) -> TokenResponse:
    """Swap a correct email and password for an access token and a refresh token."""
    user = await authenticate_user(session, email=body.email, password=body.password)
    refresh_token = await issue_refresh_token(session, user.id)
    return token_response(user, refresh_token)


@router.post("/refresh")
async def refresh(
    body: RefreshRequest, session: AsyncSession = Depends(get_db_session)
) -> TokenResponse:
    """Spend a refresh token for a new pair. Each refresh token works exactly once."""
    rotation = await rotate_refresh_token(session, body.refresh_token)
    return token_response(rotation.user, rotation.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: RefreshRequest, session: AsyncSession = Depends(get_db_session)) -> None:
    """End this login: its refresh tokens stop working. Always 204, even for unknown tokens.

    The current access token keeps working until it expires (at most 15
    minutes), because access tokens are checked without the database.
    """
    await revoke_refresh_token_family(session, body.refresh_token)
