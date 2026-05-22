"""Contract test configuration — parametrized over MockProvider and E2BProvider."""

from __future__ import annotations

import os

import pytest

from tests.conftest import MockProvider

E2B_API_KEY = os.environ.get("E2B_API_KEY")


@pytest.fixture(params=["mock", "e2b"])
async def provider(request):
    """Parametrized fixture: runs each contract test against both providers.

    The mock param always runs (fast, no network).
    The e2b param skips when E2B_API_KEY is not set.
    """
    if request.param == "e2b":
        if not E2B_API_KEY:
            pytest.skip("E2B_API_KEY not set")
        from harnessbox._providers.e2b import E2BProvider

        p = E2BProvider(api_key=E2B_API_KEY, timeout=120)
        await p.create()
        yield p
        await p.kill()
    else:
        p = MockProvider()
        await p.create()
        yield p
