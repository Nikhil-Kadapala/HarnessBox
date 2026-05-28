"""Cloud billing routes — subscription and usage info."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from harnessbox_api.auth import AuthenticatedUser, get_current_user
from harnessbox_api.billing import Subscription, get_subscription

router = APIRouter(prefix="/v1/billing", tags=["billing"])


@router.get("/subscription")
async def get_subscription_info(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    subscription: Annotated[Subscription, Depends(get_subscription)],
) -> dict[str, object]:
    return {
        "user_id": user.user_id,
        "plan": subscription.plan.value,
        "workspace_limit": subscription.workspace_limit,
        "is_active": subscription.is_active,
    }


@router.get("/usage")
async def get_usage(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    subscription: Annotated[Subscription, Depends(get_subscription)],
) -> dict[str, object]:
    return {
        "user_id": user.user_id,
        "plan": subscription.plan.value,
        "workspace_limit": subscription.workspace_limit,
        "workspaces_used": 0,  # TODO: query from workspace manager
    }
