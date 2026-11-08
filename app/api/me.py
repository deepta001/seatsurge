"""GET /me: "who am I?", answered from the access token alone (no database query).

The first protected route. Later, GET /me/orders (Phase C) lives here too.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.dependencies import get_current_user
from app.core.tokens import AccessTokenClaims
from app.db.models import UserRole

router = APIRouter(tags=["me"])


class MeResponse(BaseModel):
    user_id: int
    role: UserRole


@router.get("/me")
async def read_me(current_user: AccessTokenClaims = Depends(get_current_user)) -> MeResponse:
    """Who the access token says you are. Returns 401 without a valid token."""
    return MeResponse(user_id=current_user.user_id, role=current_user.role)
