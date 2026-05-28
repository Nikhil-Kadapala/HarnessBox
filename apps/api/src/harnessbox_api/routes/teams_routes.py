"""Cloud teams routes — team management stubs."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from harnessbox_api.auth import AuthenticatedUser, get_current_user

router = APIRouter(prefix="/v1/teams", tags=["teams"])


@router.get("/")
async def list_teams(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> dict[str, object]:
    return {
        "teams": [],
        "owner_id": user.user_id,
    }


@router.post("/invite")
async def invite_member(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> dict[str, object]:
    return {
        "status": "not_implemented",
        "message": "Team invitations coming soon",
    }
