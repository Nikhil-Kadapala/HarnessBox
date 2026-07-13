"""Tests for async workspace creation (202 pattern)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from harnessbox._server.registry import WorkspaceConfig, WorkspaceRegistry
from harnessbox._server.workspace_manager import WorkspaceManager
from harnessbox.lifecycle import RuntimeState


class TestRegisterWorkspace:
    """register_workspace() returns immediately in STARTING state."""

    def test_returns_starting_state(self) -> None:
        registry = WorkspaceRegistry()
        config = WorkspaceConfig(provider="e2b", harness="claude-code")

        info = registry.register_workspace(config, workspace_id="w-1")

        assert info.workspace_id == "w-1"
        assert info.runtime_state == RuntimeState.STARTING.value
        assert info.sandbox_conn is None
        assert info.error_message is None

    def test_workspace_is_in_registry(self) -> None:
        registry = WorkspaceRegistry()
        config = WorkspaceConfig(provider="e2b", harness="claude-code")

        info = registry.register_workspace(config, workspace_id="w-1")
        found = registry.get_workspace("w-1")

        assert found is info


class TestProvisionWorkspace:
    """provision_workspace() transitions to ACTIVE on success, ERROR on failure."""

    @pytest.mark.asyncio
    async def test_provision_success(self) -> None:
        registry = WorkspaceRegistry()
        config = WorkspaceConfig(provider="e2b", harness="claude-code")

        registry.register_workspace(config, workspace_id="w-1")

        with patch("harnessbox._server.registry.Sandbox") as MockSandbox:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance.sandbox_id = "sb-123"
            instance.event_buffer = MagicMock()
            instance.event_buffer.push = AsyncMock()
            instance._event_buffer = instance.event_buffer

            info = await registry.provision_workspace("w-1", config)

        assert info.runtime_state == RuntimeState.ACTIVE.value
        assert info.sandbox_conn is not None
        assert info.provider_sandbox_id == "sb-123"
        assert info.error_message is None

    @pytest.mark.asyncio
    async def test_provision_failure_transitions_to_error(self) -> None:
        registry = WorkspaceRegistry()
        config = WorkspaceConfig(provider="e2b", harness="claude-code")

        registry.register_workspace(config, workspace_id="w-1")

        with patch("harnessbox._server.registry.Sandbox") as MockSandbox:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock(side_effect=RuntimeError("E2B quota exceeded"))
            instance.sandbox_id = "sb-fail"

            info = await registry.provision_workspace("w-1", config)

        assert info.runtime_state == RuntimeState.ERROR.value
        assert info.error_message == "E2B quota exceeded"
        assert info.sandbox_conn is None


class TestManagerAsyncCreation:
    """WorkspaceManager exposes register + provision split."""

    def test_register_returns_starting(self) -> None:
        mgr = WorkspaceManager()
        config = WorkspaceConfig(provider="e2b", harness="claude-code")

        info = mgr.register_workspace(config, workspace_id="w-1")

        assert info.runtime_state == RuntimeState.STARTING.value

    @pytest.mark.asyncio
    async def test_provision_starts_idle_timer_on_success(self) -> None:
        mgr = WorkspaceManager()
        config = WorkspaceConfig(provider="e2b", harness="claude-code")

        mgr.register_workspace(config, workspace_id="w-1")

        with patch("harnessbox._server.registry.Sandbox") as MockSandbox:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance.sandbox_id = "sb-1"
            instance.event_buffer = MagicMock()
            instance.event_buffer.push = AsyncMock()
            instance._event_buffer = instance.event_buffer

            info = await mgr.provision_workspace("w-1", config)

        assert info.runtime_state == RuntimeState.ACTIVE.value
        assert "w-1" in mgr.idle._idle_timers

    @pytest.mark.asyncio
    async def test_provision_does_not_start_timer_on_error(self) -> None:
        mgr = WorkspaceManager()
        config = WorkspaceConfig(provider="e2b", harness="claude-code")

        mgr.register_workspace(config, workspace_id="w-1")

        with patch("harnessbox._server.registry.Sandbox") as MockSandbox:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock(side_effect=RuntimeError("fail"))
            instance.sandbox_id = "sb-1"

            await mgr.provision_workspace("w-1", config)

        assert "w-1" not in mgr.idle._idle_timers


class TestErrorStateLifecycle:
    """ERROR is a terminal state — no transitions out."""

    def test_starting_can_transition_to_error(self) -> None:
        from harnessbox.lifecycle import validate_runtime_transition

        assert validate_runtime_transition(RuntimeState.STARTING, RuntimeState.ERROR)

    def test_error_is_terminal(self) -> None:
        from harnessbox.lifecycle import validate_runtime_transition

        assert not validate_runtime_transition(RuntimeState.ERROR, RuntimeState.ACTIVE)
        assert not validate_runtime_transition(RuntimeState.ERROR, RuntimeState.DEAD)

    def test_error_state_exposed_in_session_response(self) -> None:
        from harnessbox._server.registry import WorkspaceInstance
        from harnessbox._server.routers._deps import session_response

        info = WorkspaceInstance(
            workspace_id="w-err",
            remote="",
            branch="",
            provider="e2b",
            provider_sandbox_id=None,
            snapshot_id=None,
            runtime_state=RuntimeState.ERROR.value,
            created_at="2026-01-01T00:00:00Z",
            last_active="2026-01-01T00:00:00Z",
            error_message="Sandbox quota exceeded",
        )

        resp = session_response(info)
        assert resp.runtime_state == "error"
        assert resp.error_message == "Sandbox quota exceeded"


class TestLoadWorkspacesRecovery:
    """Workspaces stuck in STARTING are recovered as ERROR on load."""

    @pytest.mark.asyncio
    async def test_starting_recovered_as_error(self) -> None:
        from harnessbox._server._storage.memory import MemoryBackend

        storage = MemoryBackend()
        await storage.initialize()
        await storage.save_workspace(
            {
                "workspace_id": "w-stuck",
                "remote": "",
                "branch": "",
                "provider": "e2b",
                "provider_sandbox_id": None,
                "snapshot_id": None,
                "harness": "claude-code",
                "runtime_state": "starting",
                "created_at": "2026-01-01T00:00:00Z",
                "last_active": "2026-01-01T00:00:00Z",
                "config_json": "{}",
            }
        )

        registry = WorkspaceRegistry(storage)
        await registry.load_workspaces()

        info = registry.get_workspace("w-stuck")
        assert info.runtime_state == RuntimeState.ERROR.value
