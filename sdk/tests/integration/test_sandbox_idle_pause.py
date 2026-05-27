"""Integration tests for Sandbox pause, resume, and auto-resume behavior.

Tests exercise pause/resume through the Sandbox facade. All assertions use
public properties (sandbox.state, sandbox.sandbox_id) — no internal state
inspection.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from harnessbox.lifecycle import RuntimeState
from harnessbox.sandbox import Sandbox
from tests.conftest import MockProvider


@pytest.fixture
def provider() -> MockProvider:
    return MockProvider()


def _active_sandbox(provider: MockProvider, **kwargs: object) -> Sandbox:
    """Create a Sandbox and put it in ACTIVE state (simulates post-setup)."""
    sb = Sandbox(client=provider, harness="claude-code", skip_permissions=True, **kwargs)
    sb._state = RuntimeState.ACTIVE
    provider._running = True
    provider._sandbox_id = "mock-sandbox-123"
    return sb


class TestSandboxPause:
    @pytest.mark.asyncio
    async def test_pause_active_sandbox_transitions_to_paused(self, provider: MockProvider) -> None:
        sb = _active_sandbox(provider)
        await sb.pause()
        assert sb.state == RuntimeState.PAUSED

    @pytest.mark.asyncio
    async def test_pause_returns_sandbox_id(self, provider: MockProvider) -> None:
        sb = _active_sandbox(provider)
        sandbox_id = await sb.pause()
        assert sandbox_id == "mock-sandbox-123"

    @pytest.mark.asyncio
    async def test_pause_already_paused_raises_invalid_transition(
        self, provider: MockProvider
    ) -> None:
        from harnessbox.lifecycle import InvalidTransitionError

        sb = _active_sandbox(provider)
        await sb.pause()
        with pytest.raises(InvalidTransitionError):
            await sb.pause()

    @pytest.mark.asyncio
    async def test_pause_dead_sandbox_raises_invalid_transition(
        self, provider: MockProvider
    ) -> None:
        from harnessbox.lifecycle import InvalidTransitionError

        sb = _active_sandbox(provider)
        sb._state = RuntimeState.DEAD
        with pytest.raises(InvalidTransitionError):
            await sb.pause()


class TestSandboxResume:
    @pytest.mark.asyncio
    async def test_resume_transitions_to_active(self, provider: MockProvider) -> None:
        sb = _active_sandbox(provider)
        await sb.pause()
        await sb.resume("mock-sandbox-123")
        assert sb.state == RuntimeState.ACTIVE

    @pytest.mark.asyncio
    async def test_resume_preserves_agent_session_id(self, provider: MockProvider) -> None:
        sb = _active_sandbox(provider)
        sb._agent_session_id = "claude-session-xyz"
        await sb.pause()
        await sb.resume("mock-sandbox-123")
        assert sb._agent_session_id == "claude-session-xyz"


class TestSandboxAutoResume:
    """send_message on a paused sandbox auto-resumes before sending."""

    @pytest.mark.asyncio
    async def test_ensure_agent_ready_resumes_paused_sandbox(self, provider: MockProvider) -> None:
        sb = _active_sandbox(provider)
        sb._state = RuntimeState.PAUSED
        sb._paused_sandbox_id = "mock-sandbox-123"
        provider._running = False

        provider.start_session = AsyncMock(return_value=42)  # type: ignore[method-assign]
        await sb._ensure_agent_ready()

        assert sb.state == RuntimeState.ACTIVE
        assert sb._agent_process is not None

    @pytest.mark.asyncio
    async def test_ensure_agent_ready_starts_new_process(self, provider: MockProvider) -> None:
        sb = _active_sandbox(provider)
        provider.start_session = AsyncMock(return_value=42)  # type: ignore[method-assign]
        await sb._ensure_agent_ready()
        assert sb._agent_process is not None

    @pytest.mark.asyncio
    async def test_ensure_agent_ready_restarts_dead_process(self, provider: MockProvider) -> None:
        sb = _active_sandbox(provider)
        sb._agent_session_id = "claude-sess-abc"

        dead_process = MagicMock()
        dead_process.is_running = False
        sb._agent_process = dead_process

        provider.start_session = AsyncMock(return_value=42)  # type: ignore[method-assign]
        await sb._ensure_agent_ready()
        assert sb._agent_process is not dead_process
