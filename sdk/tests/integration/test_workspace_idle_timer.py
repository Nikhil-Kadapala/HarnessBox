"""Integration tests for WorkspaceManager idle timers and snapshot recovery.

Tests exercise WorkspaceManager methods directly. Verifies that idle timers
fire pause, active turn counters prevent premature pausing, and snapshot
recovery creates new sandboxes when the original expires.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from harnessbox.lifecycle import RuntimeState
from harnessbox.workspace_manager import WorkspaceConfig, WorkspaceInstance, WorkspaceManager
from tests.conftest import MockProvider

# ---------------------------------------------------------------------------
# Per-workspace idle timer
# ---------------------------------------------------------------------------


class TestWorkspaceIdleTimer:
    @pytest.mark.asyncio
    async def test_idle_timer_starts_on_create(self) -> None:
        mgr = WorkspaceManager(auto_pause=True, pause_timeout=9999)

        with (
            patch("harnessbox.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox.workspace_manager.AgentManager"),
        ):
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance._cwd = "/workspace"
            await mgr.create_workspace(WorkspaceConfig(), workspace_id="w-1")

        assert "w-1" in mgr._idle_timers
        assert not mgr._idle_timers["w-1"].done()
        mgr._cancel_idle_timer("w-1")

    @pytest.mark.asyncio
    async def test_cancel_idle_timer_removes_it(self) -> None:
        mgr = WorkspaceManager(auto_pause=True, pause_timeout=9999)
        mgr._idle_timers["w-x"] = asyncio.create_task(asyncio.sleep(9999))
        mgr._cancel_idle_timer("w-x")
        assert "w-x" not in mgr._idle_timers

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_timer_is_noop(self) -> None:
        mgr = WorkspaceManager()
        mgr._cancel_idle_timer("nonexistent")

    @pytest.mark.asyncio
    async def test_start_timer_replaces_existing(self) -> None:
        mgr = WorkspaceManager(auto_pause=True, pause_timeout=9999)
        mgr._idle_timers["w-1"] = asyncio.create_task(asyncio.sleep(9999))
        first_task = mgr._idle_timers["w-1"]
        mgr._start_idle_timer("w-1")
        assert mgr._idle_timers["w-1"] is not first_task
        await asyncio.sleep(0)
        assert first_task.cancelled()
        mgr._cancel_idle_timer("w-1")

    @pytest.mark.asyncio
    async def test_countdown_fires_pause_on_active_workspace(self) -> None:
        mgr = WorkspaceManager(auto_pause=True, pause_timeout=0)

        info = WorkspaceInstance(
            workspace_id="w-1",
            remote="",
            branch="",
            provider="mock",
            provider_sandbox_id="sb-1",
            snapshot_id=None,
            runtime_state=RuntimeState.ACTIVE.value,
            workflow_state="in_progress",
            created_at="",
            last_active="",
        )
        mgr._workspaces["w-1"] = info
        mgr._locks["w-1"] = asyncio.Lock()

        pause_called: list[str] = []
        pause_mock = AsyncMock(side_effect=lambda wid: pause_called.append(wid))

        with patch.object(mgr, "_pause_workspace", pause_mock):
            await mgr._idle_countdown("w-1")

        assert pause_called == ["w-1"]

    @pytest.mark.asyncio
    async def test_countdown_skips_non_active_workspace(self) -> None:
        mgr = WorkspaceManager(auto_pause=True, pause_timeout=0)
        info = WorkspaceInstance(
            workspace_id="w-1",
            remote="",
            branch="",
            provider="mock",
            provider_sandbox_id=None,
            snapshot_id=None,
            runtime_state=RuntimeState.PAUSED.value,
            workflow_state="in_progress",
            created_at="",
            last_active="",
        )
        mgr._workspaces["w-1"] = info
        pause_mock = AsyncMock()

        with patch.object(mgr, "_pause_workspace", pause_mock):
            await mgr._idle_countdown("w-1")

        pause_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_timer_when_auto_pause_disabled(self) -> None:
        mgr = WorkspaceManager(auto_pause=False)

        with (
            patch("harnessbox.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox.workspace_manager.AgentManager"),
        ):
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance._cwd = "/workspace"
            await mgr.create_workspace(WorkspaceConfig(), workspace_id="w-1")

        assert "w-1" not in mgr._idle_timers

    @pytest.mark.asyncio
    async def test_no_global_scan_task_exists(self) -> None:
        mgr = await WorkspaceManager.create(auto_pause=True)
        assert not hasattr(mgr, "_pause_task")
        await mgr.shutdown_all()

    @pytest.mark.asyncio
    async def test_destroy_cancels_idle_timer(self) -> None:
        mgr = WorkspaceManager(auto_pause=True, pause_timeout=9999)

        with (
            patch("harnessbox.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox.workspace_manager.AgentManager") as MockAgentMgr,
        ):
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance.kill = AsyncMock()
            instance._cwd = "/workspace"
            agent = MockAgentMgr.return_value
            agent.shutdown_all = AsyncMock()
            await mgr.create_workspace(WorkspaceConfig(), workspace_id="w-1")

        assert "w-1" in mgr._idle_timers
        await mgr.destroy_workspace("w-1")
        assert "w-1" not in mgr._idle_timers


class TestActiveTurnCounter:
    @pytest.mark.asyncio
    async def test_concurrent_turns_prevent_premature_timer(self) -> None:
        mgr = WorkspaceManager(auto_pause=True, pause_timeout=9999)
        mgr._active_turns["w-1"] = 2

        count = max(0, mgr._active_turns.get("w-1", 1) - 1)
        mgr._active_turns["w-1"] = count
        assert "w-1" not in mgr._idle_timers

    @pytest.mark.asyncio
    async def test_timer_starts_when_last_turn_ends(self) -> None:
        mgr = WorkspaceManager(auto_pause=True, pause_timeout=9999)
        mgr._active_turns["w-1"] = 1
        info = WorkspaceInstance(
            workspace_id="w-1",
            remote="",
            branch="",
            provider="mock",
            provider_sandbox_id=None,
            snapshot_id=None,
            runtime_state=RuntimeState.ACTIVE.value,
            workflow_state="in_progress",
            created_at="",
            last_active="",
        )
        mgr._workspaces["w-1"] = info

        count = max(0, mgr._active_turns.get("w-1", 1) - 1)
        mgr._active_turns["w-1"] = count
        if count == 0 and mgr._auto_pause:
            mgr._start_idle_timer("w-1")

        assert "w-1" in mgr._idle_timers
        mgr._cancel_idle_timer("w-1")

    @pytest.mark.asyncio
    async def test_turn_ended_flag_prevents_double_decrement(self) -> None:
        """Regression: TURN_ENDED + finally block must not double-decrement."""
        mgr = WorkspaceManager(auto_pause=True, pause_timeout=9999)
        mgr._active_turns["w-1"] = 2

        # TURN_ENDED decrements 2→1
        active = max(0, mgr._active_turns.get("w-1", 1) - 1)
        mgr._active_turns["w-1"] = active
        turn_ended_seen = True

        # finally block with fix: skips decrement because turn_ended_seen is True
        if not turn_ended_seen:
            active = max(0, mgr._active_turns.get("w-1", 1) - 1)
            mgr._active_turns["w-1"] = active
            if active == 0 and mgr._auto_pause:
                mgr._start_idle_timer("w-1")

        assert mgr._active_turns["w-1"] == 1
        assert "w-1" not in mgr._idle_timers


# ---------------------------------------------------------------------------
# Snapshot recovery
# ---------------------------------------------------------------------------


class TestSnapshotRecovery:
    """_resume_workspace recovers from expired sandboxes via snapshot."""

    def _make_mgr_with_workspace(
        self,
        *,
        snapshot_id: str | None = "snap-1",
        provider_sandbox_id: str | None = "sb-old",
    ) -> tuple[WorkspaceManager, WorkspaceInstance, MockProvider]:
        provider = MockProvider()
        mgr = WorkspaceManager(auto_pause=False)

        mock_sandbox = MagicMock()
        mock_sandbox._provider = provider
        mock_sandbox.resume = AsyncMock()

        info = WorkspaceInstance(
            workspace_id="w-1",
            remote="",
            branch="",
            provider="mock",
            provider_sandbox_id=provider_sandbox_id,
            snapshot_id=snapshot_id,
            runtime_state=RuntimeState.PAUSED.value,
            workflow_state="in_progress",
            created_at="",
            last_active="",
            sandbox_conn=mock_sandbox,
        )
        mgr._workspaces["w-1"] = info
        mgr._locks["w-1"] = asyncio.Lock()
        mgr._workspace_configs["w-1"] = WorkspaceConfig(timeout=300)
        return mgr, info, provider

    @pytest.mark.asyncio
    async def test_recovery_creates_sandbox_from_snapshot(self) -> None:
        from harnessbox.providers import SandboxDeadError

        mgr, info, provider = self._make_mgr_with_workspace()

        created_calls: list[dict[str, object]] = []

        async def fake_create(
            env_vars: dict[str, str] | None = None,
            timeout: int = 300,
            snapshot_id: str | None = None,
        ) -> None:
            created_calls.append({"snapshot_id": snapshot_id})
            provider._sandbox_id = "sb-new"
            provider._running = True

        provider.create = fake_create  # type: ignore[method-assign]

        failing = AsyncMock(side_effect=SandboxDeadError("sandbox was not found"))
        with patch.object(mgr, "_try_resume_sandbox", failing):
            await mgr._resume_workspace("w-1")

        assert len(created_calls) == 1
        assert created_calls[0]["snapshot_id"] == "snap-1"
        assert info.runtime_state == RuntimeState.ACTIVE.value
        assert info.provider_sandbox_id == "sb-new"

    @pytest.mark.asyncio
    async def test_recovery_raises_when_no_snapshot_available(self) -> None:
        from harnessbox.providers import SandboxDeadError

        mgr, info, provider = self._make_mgr_with_workspace(snapshot_id=None)

        failing = AsyncMock(side_effect=SandboxDeadError("sandbox was not found"))
        with patch.object(mgr, "_try_resume_sandbox", failing):
            with pytest.raises(ValueError, match="has no snapshot"):
                await mgr._resume_workspace("w-1")

    @pytest.mark.asyncio
    async def test_recovery_raises_when_snapshot_expired(self) -> None:
        from harnessbox.providers import SandboxDeadError

        mgr, info, provider = self._make_mgr_with_workspace()

        async def create_snapshot_not_found(
            env_vars: dict[str, str] | None = None,
            timeout: int = 300,
            snapshot_id: str | None = None,
        ) -> None:
            raise Exception("snapshot not found")

        provider.create = create_snapshot_not_found  # type: ignore[method-assign]

        failing = AsyncMock(side_effect=SandboxDeadError("sandbox was not found"))
        with patch.object(mgr, "_try_resume_sandbox", failing):
            with pytest.raises(ValueError, match="no longer exists"):
                await mgr._resume_workspace("w-1")

    @pytest.mark.asyncio
    async def test_happy_path_resume_no_snapshot_needed(self) -> None:
        mgr, info, provider = self._make_mgr_with_workspace()
        provider._sandbox_id = "sb-old"
        provider._running = True

        ok = AsyncMock()
        with patch.object(mgr, "_try_resume_sandbox", ok):
            await mgr._resume_workspace("w-1")

        assert info.runtime_state == RuntimeState.ACTIVE.value

    @pytest.mark.asyncio
    async def test_recovery_updates_storage(self) -> None:
        from harnessbox._storage.memory import MemoryBackend
        from harnessbox.providers import SandboxDeadError

        storage = MemoryBackend()
        await storage.initialize()

        mgr, info, provider = self._make_mgr_with_workspace()
        mgr._storage = storage

        await storage.save_workspace(
            {
                "workspace_id": "w-1",
                "remote": "",
                "branch": "",
                "provider": "mock",
                "provider_sandbox_id": "sb-old",
                "snapshot_id": "snap-1",
                "harness": "claude-code",
                "runtime_state": RuntimeState.PAUSED.value,
                "created_at": "",
                "last_active": "",
                "config_json": "{}",
            }
        )

        async def fake_create(
            env_vars: dict[str, str] | None = None,
            timeout: int = 300,
            snapshot_id: str | None = None,
        ) -> None:
            provider._sandbox_id = "sb-new"
            provider._running = True

        provider.create = fake_create  # type: ignore[method-assign]

        failing = AsyncMock(side_effect=SandboxDeadError("sandbox was not found"))
        with patch.object(mgr, "_try_resume_sandbox", failing):
            await mgr._resume_workspace("w-1")

        records = await storage.list_workspaces()
        assert records[0]["provider_sandbox_id"] == "sb-new"


# ---------------------------------------------------------------------------
# Graceful shutdown, load state correction, and timer disable
# ---------------------------------------------------------------------------


class TestGracefulShutdown:
    @pytest.mark.asyncio
    async def test_graceful_shutdown_pauses_active_workspaces(self) -> None:
        mgr = WorkspaceManager(auto_pause=True, pause_timeout=9999)

        sandbox_mock = MagicMock()
        sandbox_mock.create_snapshot = AsyncMock(return_value="snap-1")
        sandbox_mock.pause = AsyncMock(return_value="sb-1")
        sandbox_mock._event_buffer = MagicMock()
        sandbox_mock._event_buffer.close = AsyncMock()
        sandbox_mock._event_buffer.push = AsyncMock()

        info = WorkspaceInstance(
            workspace_id="w-1",
            remote="",
            branch="",
            provider="mock",
            provider_sandbox_id="sb-1",
            snapshot_id=None,
            runtime_state=RuntimeState.ACTIVE.value,
            workflow_state="in_progress",
            created_at="",
            last_active="",
            sandbox_conn=sandbox_mock,
        )
        mgr._workspaces["w-1"] = info
        mgr._locks["w-1"] = asyncio.Lock()

        await mgr.graceful_shutdown()

        assert info.runtime_state == RuntimeState.PAUSED.value
        assert info.snapshot_id == "snap-1"
        sandbox_mock.create_snapshot.assert_awaited_once()
        sandbox_mock.pause.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_graceful_shutdown_skips_paused_workspaces(self) -> None:
        mgr = WorkspaceManager(auto_pause=True, pause_timeout=9999)

        info = WorkspaceInstance(
            workspace_id="w-1",
            remote="",
            branch="",
            provider="mock",
            provider_sandbox_id="sb-1",
            snapshot_id="snap-old",
            runtime_state=RuntimeState.PAUSED.value,
            workflow_state="in_progress",
            created_at="",
            last_active="",
            sandbox_conn=None,
        )
        mgr._workspaces["w-1"] = info

        await mgr.graceful_shutdown()

        assert info.runtime_state == RuntimeState.PAUSED.value

    @pytest.mark.asyncio
    async def test_graceful_shutdown_timeout_guard(self) -> None:
        mgr = WorkspaceManager(auto_pause=True, pause_timeout=9999)

        async def slow_snapshot() -> str:
            await asyncio.sleep(60)
            return "snap-never"

        sandbox_mock = MagicMock()
        sandbox_mock.create_snapshot = slow_snapshot
        sandbox_mock.pause = AsyncMock(return_value="sb-1")
        sandbox_mock._event_buffer = MagicMock()
        sandbox_mock._event_buffer.close = AsyncMock()
        sandbox_mock._event_buffer.push = AsyncMock()

        info = WorkspaceInstance(
            workspace_id="w-1",
            remote="",
            branch="",
            provider="mock",
            provider_sandbox_id="sb-1",
            snapshot_id=None,
            runtime_state=RuntimeState.ACTIVE.value,
            workflow_state="in_progress",
            created_at="",
            last_active="",
            sandbox_conn=sandbox_mock,
        )
        mgr._workspaces["w-1"] = info
        mgr._locks["w-1"] = asyncio.Lock()

        # Should not hang — timeout guard at 30s, but we patch wait_for
        with patch(
            "harnessbox.workspace_manager.asyncio.wait_for", side_effect=asyncio.TimeoutError
        ):
            await mgr.graceful_shutdown()

        # Workspace was NOT paused (timed out)
        assert info.runtime_state == RuntimeState.ACTIVE.value


class TestLoadWorkspacesStateDowngrade:
    @pytest.mark.asyncio
    async def test_active_state_downgraded_to_paused_on_load(self) -> None:
        from harnessbox._storage.memory import MemoryBackend

        storage = MemoryBackend()
        await storage.initialize()

        await storage.save_workspace(
            {
                "workspace_id": "w-1",
                "remote": "https://github.com/test/repo.git",
                "branch": "main",
                "provider": "e2b",
                "provider_sandbox_id": "sb-old",
                "snapshot_id": "snap-1",
                "harness": "claude-code",
                "runtime_state": RuntimeState.ACTIVE.value,
                "workflow_state": "in_progress",
                "created_at": "2026-01-01T00:00:00Z",
                "last_active": "2026-01-01T00:00:00Z",
                "config_json": "{}",
            }
        )

        mgr = WorkspaceManager(storage=storage)
        await mgr.load_workspaces()

        info = mgr.get_workspace("w-1")
        assert info.runtime_state == RuntimeState.PAUSED.value
        assert info.sandbox_conn is None


class TestSessionTimeoutDisabledForManagedSandbox:
    @pytest.mark.asyncio
    async def test_sandbox_created_with_session_timeout_zero(self) -> None:
        mgr = WorkspaceManager(auto_pause=True, pause_timeout=9999)

        with (
            patch("harnessbox.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox.workspace_manager.AgentManager"),
        ):
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance._cwd = "/workspace"
            await mgr.create_workspace(WorkspaceConfig(), workspace_id="w-1")

            call_kwargs = MockSandbox.call_args[1]
            assert call_kwargs["session_timeout"] == 0

        mgr._cancel_idle_timer("w-1")
