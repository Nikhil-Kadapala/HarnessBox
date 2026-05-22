"""E2E test configuration — requires E2B_API_KEY environment variable."""

from __future__ import annotations

import os

import pytest

E2B_API_KEY = os.environ.get("E2B_API_KEY")

TEST_FIXTURE_REPO = "https://github.com/Nikhil-Kadapala/harnessbox-test-fixture.git"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip E2E tests when E2B_API_KEY is not set, and apply e2e marker."""
    skip = pytest.mark.skip(reason="E2B_API_KEY not set — skipping E2E tests")
    for item in items:
        if "/e2e/" in str(item.fspath):
            item.add_marker(pytest.mark.e2e)
            if not E2B_API_KEY:
                item.add_marker(skip)


@pytest.fixture
async def e2b_provider():
    """Create a real E2B sandbox, yield provider, kill on teardown."""
    from harnessbox._providers.e2b import E2BProvider

    provider = E2BProvider(api_key=E2B_API_KEY, timeout=120)
    await provider.create()
    yield provider
    await provider.kill()
