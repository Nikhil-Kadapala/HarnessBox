"""Unit tests for E2B provider timeout extension logic.

Tests verify the public interface: notify_turn_start(), notify_turn_end(),
maybe_extend_timeout(). No internal state inspection.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from harnessbox._providers.e2b import E2BProvider


def _make_provider(timeout: int = 300) -> E2BProvider:
    """Construct an E2BProvider for unit testing without a real E2B sandbox."""
    p = E2BProvider.__new__(E2BProvider)
    p._api_key = "test"
    p._template = "base"
    p._timeout = timeout
    p._sandbox = MagicMock()
    p._sandbox.set_timeout = AsyncMock()
    p._turn_start_time = None
    p._total_extensions = 0
    p._extended_this_turn = False
    return p


class TestE2BTimeoutExtension:
    """E2B provider extends sandbox TTL when a turn runs past the halfway mark."""

    @pytest.mark.asyncio
    async def test_no_extension_before_halfway_returns_false(self) -> None:
        p = _make_provider(timeout=300)
        p.notify_turn_start()
        p._turn_start_time = time.monotonic() - 10  # 10s elapsed, halfway is 150s
        assert await p.maybe_extend_timeout() is False

    @pytest.mark.asyncio
    async def test_extension_after_halfway_returns_true(self) -> None:
        p = _make_provider(timeout=300)
        p.notify_turn_start()
        p._turn_start_time = time.monotonic() - 160  # past 150s halfway
        assert await p.maybe_extend_timeout() is True

    @pytest.mark.asyncio
    async def test_extension_calls_set_timeout_with_valid_value(self) -> None:
        p = _make_provider(timeout=300)
        p.notify_turn_start()
        p._turn_start_time = time.monotonic() - 160
        await p.maybe_extend_timeout()
        call_arg = p._sandbox.set_timeout.call_args[0][0]
        # remaining (~140) + extension (150) ≈ 290
        assert 270 <= call_arg <= 310

    @pytest.mark.asyncio
    async def test_at_most_one_extension_per_turn(self) -> None:
        p = _make_provider(timeout=300)
        p.notify_turn_start()
        p._turn_start_time = time.monotonic() - 200
        assert await p.maybe_extend_timeout() is True
        assert await p.maybe_extend_timeout() is False
        assert await p.maybe_extend_timeout() is False

    @pytest.mark.asyncio
    async def test_new_turn_allows_extension_again(self) -> None:
        p = _make_provider(timeout=300)
        p.notify_turn_start()
        p._turn_start_time = time.monotonic() - 200
        await p.maybe_extend_timeout()

        p.notify_turn_end()
        p.notify_turn_start()
        p._turn_start_time = time.monotonic() - 200
        assert await p.maybe_extend_timeout() is True

    @pytest.mark.asyncio
    async def test_extension_budget_exhausted_returns_false(self) -> None:
        p = _make_provider(timeout=300)
        max_extra = (p._MAX_EXTENSION_MULTIPLIER - 1) * 300  # 600s
        p._total_extensions = max_extra
        p.notify_turn_start()
        p._turn_start_time = time.monotonic() - 200
        assert await p.maybe_extend_timeout() is False

    @pytest.mark.asyncio
    async def test_extension_capped_at_remaining_budget(self) -> None:
        p = _make_provider(timeout=300)
        p._total_extensions = 550  # only 50s left of 600s budget
        p.notify_turn_start()
        p._turn_start_time = time.monotonic() - 200
        assert await p.maybe_extend_timeout() is True
        # set_timeout receives remaining (~100) + capped extension (50) ≈ 150
        call_arg = p._sandbox.set_timeout.call_args[0][0]
        assert 130 <= call_arg <= 170

    @pytest.mark.asyncio
    async def test_no_extension_when_no_turn_active(self) -> None:
        p = _make_provider(timeout=300)
        assert await p.maybe_extend_timeout() is False

    @pytest.mark.asyncio
    async def test_notify_turn_end_disables_extension(self) -> None:
        p = _make_provider(timeout=300)
        p.notify_turn_start()
        p.notify_turn_end()
        # After turn ends, maybe_extend_timeout should be a no-op
        assert await p.maybe_extend_timeout() is False

    @pytest.mark.asyncio
    async def test_extension_failure_returns_false_without_raising(self) -> None:
        p = _make_provider(timeout=300)
        p._sandbox.set_timeout = AsyncMock(side_effect=Exception("network error"))
        p.notify_turn_start()
        p._turn_start_time = time.monotonic() - 200
        assert await p.maybe_extend_timeout() is False

    @pytest.mark.asyncio
    async def test_create_resets_extension_budget(self) -> None:
        p = _make_provider(timeout=300)
        p._total_extensions = 600  # fully exhausted
        p._extended_this_turn = True

        mock_sandbox = MagicMock()
        mock_sandbox.sandbox_id = "sb-new"
        mock_cls = AsyncMock(return_value=mock_sandbox)

        with patch.object(p, "_get_sdk", return_value=mock_cls):
            await p.create(timeout=300)

        # After create, extension should work again (budget reset)
        p.notify_turn_start()
        p._turn_start_time = time.monotonic() - 200
        assert await p.maybe_extend_timeout() is True
