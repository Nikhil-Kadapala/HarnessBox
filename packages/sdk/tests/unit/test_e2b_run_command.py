"""Unit tests for E2BProvider.run_command exit-code handling."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from harnessbox._providers.e2b import E2BProvider
from harnessbox.providers import SandboxDeadError


def _make_provider() -> E2BProvider:
    p = E2BProvider.__new__(E2BProvider)
    p._api_key = "test"
    p._template = "base"
    p._timeout = 300
    p._sandbox = MagicMock()
    return p


class _FakeExit(Exception):
    """Mirrors e2b CommandExitException shape (exit_code/stdout/stderr)."""

    def __init__(self, exit_code: int, stderr: str = "", stdout: str = "") -> None:
        self.exit_code = exit_code
        self.stderr = stderr
        self.stdout = stdout
        super().__init__(f"Command exited with code {exit_code}")


@pytest.mark.asyncio
async def test_run_command_returns_nonzero_exit_as_result() -> None:
    """Non-zero exits must not raise — callers inspect CommandResult.exit_code."""
    p = _make_provider()
    p._sandbox.commands.run = AsyncMock(
        side_effect=_FakeExit(128, stderr="fatal: Needed a single revision\n")
    )

    result = await p.run_command("git rev-parse --verify origin/tokyo")
    assert result.exit_code == 128
    assert "Needed a single revision" in result.stderr


@pytest.mark.asyncio
async def test_run_command_success() -> None:
    p = _make_provider()
    ok = MagicMock(exit_code=0, stdout="abc\n", stderr="")
    p._sandbox.commands.run = AsyncMock(return_value=ok)

    result = await p.run_command("echo abc")
    assert result.exit_code == 0
    assert result.stdout == "abc\n"


@pytest.mark.asyncio
async def test_run_command_dead_sandbox_still_raises() -> None:
    p = _make_provider()
    p._sandbox.commands.run = AsyncMock(side_effect=RuntimeError("sandbox was not found"))

    with pytest.raises(SandboxDeadError):
        await p.run_command("true")
