"""Cloud auth routes — user info and token refresh."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from harnessbox_api.auth import AuthenticatedUser, get_current_user

router = APIRouter(prefix="/v1/auth", tags=["auth"])


@router.get("/me")
async def get_me(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> dict[str, str | None]:
    return {
        "user_id": user.user_id,
        "email": user.email,
        "role": user.role,
    }
