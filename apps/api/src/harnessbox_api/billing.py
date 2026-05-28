"""Stripe billing dependency — customer/subscription lookup and quota enforcement."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated

import stripe
from fastapi import Depends, HTTPException, status

from harnessbox_api.auth import AuthenticatedUser, get_current_user
from harnessbox_api.config import Settings, get_settings


class Plan(StrEnum):
    FREE = "free"
    PRO = "pro"
    TEAM = "team"


@dataclass(frozen=True, slots=True)
class Subscription:
    customer_id: str | None
    plan: Plan
    workspace_limit: int
    is_active: bool


_PLAN_LIMITS: dict[Plan, int] = {
    Plan.FREE: 2,
    Plan.PRO: 20,
    Plan.TEAM: 100,
}


async def get_subscription(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Subscription:
    stripe.api_key = settings.stripe_secret_key

    customers = stripe.Customer.search(
        query=f'metadata["supabase_user_id"]:"{user.user_id}"',
    )

    if not customers.data:
        return Subscription(
            customer_id=None,
            plan=Plan.FREE,
            workspace_limit=_PLAN_LIMITS[Plan.FREE],
            is_active=True,
        )

    customer = customers.data[0]
    subscriptions = stripe.Subscription.list(customer=customer.id, status="active", limit=1)

    if not subscriptions.data:
        return Subscription(
            customer_id=customer.id,
            plan=Plan.FREE,
            workspace_limit=_PLAN_LIMITS[Plan.FREE],
            is_active=True,
        )

    sub = subscriptions.data[0]
    plan_name = sub.metadata.get("plan", "pro")  # type: ignore[operator]
    plan_lookup: dict[str, Plan] = {p.value: p for p in Plan}
    plan = plan_lookup.get(str(plan_name), Plan.PRO)

    return Subscription(
        customer_id=customer.id,
        plan=plan,
        workspace_limit=_PLAN_LIMITS[plan],
        is_active=True,
    )


async def require_active_subscription(
    subscription: Annotated[Subscription, Depends(get_subscription)],
) -> Subscription:
    if not subscription.is_active:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Active subscription required",
        )
    return subscription
