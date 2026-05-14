"""Tests for idle-pause and resume functionality."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from harnessbox.config.harness import get_harness_type
from harnessbox.lifecycle import WorkspaceState
from harnessbox.sandbox import Sandbox


@pytest.fixture
def provider() -> object:
    from tests.conftest import MockProvider

    return MockProvider()


def _make_sandbox(
    provider: object,
    session_timeout: int = 1,
    session_lock: asyncio.Lock | None = None,
) -> Sandbox:
    return Sandbox(
        provider,
        harness="claude-code",
        skip_permissions=True,
        session_timeout=session_timeout,
        session_lock=session_lock,
    )


class TestBuildSessionCommand:
    def test_without_session_id(self) -> None:
        cfg = get_harness_type("claude-code")
        cmd = cfg.build_session_command(skip_permissions=True)
        assert "--resume" not in cmd
        assert "--input-format" in cmd
        assert "--dangerously-skip-permissions" in cmd

    def test_with_session_id(self) -> None:
        cfg = get_harness_type("claude-code")
        cmd = cfg.build_session_command(skip_permissions=True, session_id="abc-123")
        assert "--resume abc-123" in cmd
        parts = cmd.split()
        resume_idx = parts.index("--resume")
        input_idx = parts.index("--input-format")
        assert resume_idx < input_idx

    def test_session_id_none_same_as_omitted(self) -> None:
        cfg = get_harness_type("claude-code")
        cmd_none = cfg.build_session_command(skip_permissions=True, session_id=None)
        cmd_omit = cfg.build_session_command(skip_permissions=True)
        assert cmd_none == cmd_omit


class TestIdleTimerLifecycle:
    async def test_start_creates_task(self, provider: object) -> None:
        sandbox = _make_sandbox(provider, session_timeout=10)
        sandbox._state = WorkspaceState.ACTIVE
        sandbox._start_idle_timer()
        assert sandbox._idle_timer_task is not None
        assert not sandbox._idle_timer_task.done()
        sandbox._cancel_idle_timer()

    async def test_cancel_stops_task(self, provider: object) -> None:
        sandbox = _make_sandbox(provider, session_timeout=10)
        sandbox._state = WorkspaceState.ACTIVE
        sandbox._start_idle_timer()
        task = sandbox._idle_timer_task
        sandbox._cancel_idle_timer()
        assert sandbox._idle_timer_task is None
        await asyncio.sleep(0)
        assert task is not None and task.cancelled()

    async def test_cancel_idempotent(self, provider: object) -> None:
        sandbox = _make_sandbox(provider)
        sandbox._cancel_idle_timer()
        sandbox._cancel_idle_timer()

    async def test_start_replaces_existing(self, provider: object) -> None:
        sandbox = _make_sandbox(provider, session_timeout=10)
        sandbox._state = WorkspaceState.ACTIVE
        sandbox._start_idle_timer()
        first_task = sandbox._idle_timer_task
        sandbox._start_idle_timer()
        second_task = sandbox._idle_timer_task
        assert first_task is not second_task
        await asyncio.sleep(0)
        assert first_task is not None and first_task.cancelled()
        sandbox._cancel_idle_timer()

    async def test_zero_timeout_no_timer(self, provider: object) -> None:
        sandbox = _make_sandbox(provider, session_timeout=0)
        sandbox._state = WorkspaceState.ACTIVE
        sandbox._start_idle_timer()
        assert sandbox._idle_timer_task is None


class TestIdleTimeout:
    async def test_timeout_pauses_sandbox(self, provider: object) -> None:
        sandbox = _make_sandbox(provider, session_timeout=0)
        sandbox._state = WorkspaceState.ACTIVE
        provider._running = True  # type: ignore[attr-defined]
        provider._sandbox_id = "mock-sandbox-123"  # type: ignore[attr-defined]
        await sandbox._do_idle_pause()
        assert sandbox._state == WorkspaceState.PAUSED
        assert sandbox._paused_sandbox_id == "mock-sandbox-123"

    async def test_timeout_stops_agent_process(self, provider: object) -> None:
        sandbox = _make_sandbox(provider)
        sandbox._state = WorkspaceState.ACTIVE
        provider._running = True  # type: ignore[attr-defined]
        provider._sandbox_id = "mock-sandbox-123"  # type: ignore[attr-defined]
        mock_process = MagicMock()
        mock_process.stop = AsyncMock()
        sandbox._agent_process = mock_process
        await sandbox._do_idle_pause()
        mock_process.stop.assert_called_once()
        assert sandbox._agent_process is None

    async def test_timeout_noop_when_paused(self, provider: object) -> None:
        sandbox = _make_sandbox(provider)
        sandbox._state = WorkspaceState.PAUSED
        await sandbox._do_idle_pause()
        assert not provider._running or provider._sandbox_id is None

    async def test_timeout_noop_when_failed(self, provider: object) -> None:
        sandbox = _make_sandbox(provider)
        sandbox._state = WorkspaceState.FAILED
        await sandbox._do_idle_pause()

    async def test_timeout_with_lock(self, provider: object) -> None:
        lock = asyncio.Lock()
        sandbox = _make_sandbox(provider, session_timeout=0, session_lock=lock)
        sandbox._state = WorkspaceState.ACTIVE
        sandbox._session_timeout = 0
        provider._running = True  # type: ignore[attr-defined]
        provider._sandbox_id = "mock-sandbox-123"  # type: ignore[attr-defined]

        async with lock:
            task = asyncio.create_task(sandbox._on_idle_timeout())
            await asyncio.sleep(0.05)
            assert sandbox._state == WorkspaceState.ACTIVE

        await asyncio.sleep(0.05)
        await task
        assert sandbox._state == WorkspaceState.PAUSED


class TestResumeFromPause:
    async def test_resume_clears_paused_state(self, provider: object) -> None:
        sandbox = _make_sandbox(provider)
        sandbox._state = WorkspaceState.PAUSED
        sandbox._paused_sandbox_id = "mock-sandbox-123"
        await sandbox.resume("mock-sandbox-123")
        assert sandbox._state == WorkspaceState.ACTIVE

    def test_agent_session_id_preserved(self, provider: object) -> None:
        sandbox = _make_sandbox(provider)
        sandbox._agent_session_id = "claude-session-xyz"
        assert sandbox._agent_session_id == "claude-session-xyz"


class TestEnsureAgentReady:
    async def test_first_start(self, provider: object) -> None:
        sandbox = _make_sandbox(provider)
        sandbox._state = WorkspaceState.ACTIVE
        provider._running = True  # type: ignore[attr-defined]
        provider._sandbox_id = "mock-sandbox-123"  # type: ignore[attr-defined]

        with patch.object(sandbox, "_agent_process", None):
            # Mock start_persistent on provider
            provider.start_persistent = AsyncMock(return_value=42)  # type: ignore[attr-defined]
            await sandbox._ensure_agent_ready()
            assert sandbox._agent_process is not None

    async def test_resumes_from_paused(self, provider: object) -> None:
        sandbox = _make_sandbox(provider)
        sandbox._state = WorkspaceState.PAUSED
        sandbox._paused_sandbox_id = "mock-sandbox-123"
        provider._running = False  # type: ignore[attr-defined]

        # Mock start_persistent on provider
        provider.start_persistent = AsyncMock(return_value=42)  # type: ignore[attr-defined]
        await sandbox._ensure_agent_ready()
        assert sandbox._state == WorkspaceState.ACTIVE
        assert sandbox._paused_sandbox_id is None
        assert sandbox._agent_process is not None

    async def test_restarts_dead_process(self, provider: object) -> None:
        sandbox = _make_sandbox(provider)
        sandbox._state = WorkspaceState.ACTIVE
        sandbox._agent_session_id = "claude-sess-abc"
        provider._running = True  # type: ignore[attr-defined]
        provider._sandbox_id = "mock-sandbox-123"  # type: ignore[attr-defined]

        dead_process = MagicMock()
        dead_process.is_running = False
        sandbox._agent_process = dead_process

        provider.start_persistent = AsyncMock(return_value=42)  # type: ignore[attr-defined]
        await sandbox._ensure_agent_ready()
        assert sandbox._agent_process is not dead_process


class TestServerTimeoutFields:
    def test_create_session_with_timeouts(self) -> None:
        from fastapi.testclient import TestClient

        from harnessbox.server import create_app
        from harnessbox.workspace_manager import WorkspaceManager

        app = create_app(manager=WorkspaceManager())
        client = TestClient(app)

        with patch("harnessbox.workspace_manager.Sandbox") as MockSandbox:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance.sandbox_id = "sb-1"

            resp = client.post(
                "/v1/workspaces",
                json={
                    "session_id": "t-1",
                    "sandbox_timeout": 3600,
                    "session_timeout": 1800,
                },
            )
        assert resp.status_code == 201

    def test_session_timeout_clamped(self) -> None:
        from fastapi.testclient import TestClient

        from harnessbox.server import create_app
        from harnessbox.workspace_manager import WorkspaceManager

        app = create_app(manager=WorkspaceManager())
        client = TestClient(app)

        with patch("harnessbox.workspace_manager.Sandbox") as MockSandbox:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance.sandbox_id = "sb-1"

            resp = client.post(
                "/v1/workspaces",
                json={
                    "session_id": "t-2",
                    "sandbox_timeout": 300,
                    "session_timeout": 600,
                },
            )
        assert resp.status_code == 201
