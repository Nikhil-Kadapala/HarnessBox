"""Unit tests for E2B post-resume Anthropic egress readiness probing."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from harnessbox._providers.e2b import (
    _EGRESS_PROBE_CMD,
    _EGRESS_PROBE_MAX_ATTEMPTS,
    _EGRESS_PROBE_URL,
    E2BProvider,
)
from harnessbox.providers import CommandResult, SandboxDeadError


def _make_provider() -> E2BProvider:
    """Construct an E2BProvider for unit testing without a real E2B sandbox."""
    p = E2BProvider.__new__(E2BProvider)
    p._api_key = "test"
    p._template = "base"
    p._timeout = 120
    p._sandbox = MagicMock()
    p._turn_start_time = None
    p._total_extensions = 0
    p._extended_this_turn = False
    return p


class TestWaitForAnthropicEgress:
    """Bounded HTTPS probe against api.anthropic.com after connect()."""

    def test_probe_command_quotes_url_inside_shell_wrapper(self) -> None:
        """The nested Python URL must not terminate the shell -c string."""
        assert f'urlopen("{_EGRESS_PROBE_URL}",' in _EGRESS_PROBE_CMD
        assert f"urlopen('{_EGRESS_PROBE_URL}'," not in _EGRESS_PROBE_CMD

    @pytest.mark.asyncio
    async def test_immediate_success_returns(self) -> None:
        p = _make_provider()
        p.run_command = AsyncMock(  # type: ignore[method-assign]
            return_value=CommandResult(exit_code=0, stdout="", stderr="")
        )

        await p._wait_for_anthropic_egress()

        assert p.run_command.await_count == 1

    @pytest.mark.asyncio
    async def test_transient_failures_then_success(self) -> None:
        p = _make_provider()
        p.run_command = AsyncMock(  # type: ignore[method-assign]
            side_effect=[
                CommandResult(exit_code=1, stdout="", stderr="URLError: timed out"),
                CommandResult(exit_code=1, stdout="", stderr="URLError: name resolution"),
                CommandResult(exit_code=0, stdout="", stderr=""),
            ]
        )

        with patch("harnessbox._providers.e2b.asyncio.sleep", new_callable=AsyncMock) as sleep:
            await p._wait_for_anthropic_egress()

        assert p.run_command.await_count == 3
        assert sleep.await_count == 2

    @pytest.mark.asyncio
    async def test_exhausted_retries_raise_runtime_error(self) -> None:
        p = _make_provider()
        p.run_command = AsyncMock(  # type: ignore[method-assign]
            return_value=CommandResult(exit_code=1, stdout="", stderr="URLError: network down")
        )

        with patch("harnessbox._providers.e2b.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RuntimeError, match=_EGRESS_PROBE_URL) as exc_info:
                await p._wait_for_anthropic_egress()

        assert p.run_command.await_count == _EGRESS_PROBE_MAX_ATTEMPTS
        assert "not ready" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_sandbox_dead_during_probe_propagates(self) -> None:
        p = _make_provider()
        p.run_command = AsyncMock(  # type: ignore[method-assign]
            side_effect=SandboxDeadError("sandbox was not found")
        )

        with pytest.raises(SandboxDeadError, match="sandbox was not found"):
            await p._wait_for_anthropic_egress()


class TestResumeRunsEgressProbe:
    """resume() must connect then wait for Anthropic egress before returning."""

    @pytest.mark.asyncio
    async def test_resume_calls_egress_wait_after_connect(self) -> None:
        p = _make_provider()
        mock_sandbox = MagicMock()
        mock_sandbox.sandbox_id = "sb-1"
        mock_cls = MagicMock()
        mock_cls.connect = AsyncMock(return_value=mock_sandbox)
        p._wait_for_anthropic_egress = AsyncMock()  # type: ignore[method-assign]

        with patch.object(p, "_get_sdk", return_value=mock_cls):
            await p.resume("sb-paused")

        mock_cls.connect.assert_awaited_once_with("sb-paused", api_key="test")
        assert p._sandbox is mock_sandbox
        p._wait_for_anthropic_egress.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_resume_propagates_egress_failure(self) -> None:
        p = _make_provider()
        mock_sandbox = MagicMock()
        mock_cls = MagicMock()
        mock_cls.connect = AsyncMock(return_value=mock_sandbox)
        p._wait_for_anthropic_egress = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("Sandbox egress to https://api.anthropic.com not ready")
        )

        with patch.object(p, "_get_sdk", return_value=mock_cls):
            with pytest.raises(RuntimeError, match="not ready"):
                await p.resume("sb-paused")
