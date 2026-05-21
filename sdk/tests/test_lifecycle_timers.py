"""Tests for issue #6: per-workspace idle timers, E2B timeout extension, snapshot recovery."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from harnessbox.lifecycle import RuntimeState
from harnessbox.workspace_manager import WorkspaceConfig, WorkspaceInstance, WorkspaceManager

from .conftest import MockProvider

# ---------------------------------------------------------------------------
# Part A: Per-workspace idle timer
# ---------------------------------------------------------------------------


class TestPerWorkspaceIdleTimer:
    """Idle timer is per-workspace and only starts after all active turns complete."""

    @pytest.mark.asyncio
    async def test_idle_timer_starts_on_create(self) -> None:
        """A fresh workspace should have an idle timer running."""
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
    async def test_cancel_idle_timer(self) -> None:
        """Cancelling an idle timer removes it."""
        mgr = WorkspaceManager(auto_pause=True, pause_timeout=9999)
        mgr._idle_timers["w-x"] = asyncio.create_task(asyncio.sleep(9999))
        mgr._cancel_idle_timer("w-x")
        assert "w-x" not in mgr._idle_timers

    @pytest.mark.asyncio
    async def test_cancel_idle_timer_idempotent(self) -> None:
        """Cancelling a non-existent timer is a no-op."""
        mgr = WorkspaceManager()
        mgr._cancel_idle_timer("nonexistent")  # should not raise

    @pytest.mark.asyncio
    async def test_start_idle_timer_replaces_existing(self) -> None:
        """Starting a new timer cancels the old one."""
        mgr = WorkspaceManager(auto_pause=True, pause_timeout=9999)
        mgr._idle_timers["w-1"] = asyncio.create_task(asyncio.sleep(9999))
        first_task = mgr._idle_timers["w-1"]
        mgr._start_idle_timer("w-1")
        assert mgr._idle_timers["w-1"] is not first_task
        await asyncio.sleep(0)
        assert first_task.cancelled()
        mgr._cancel_idle_timer("w-1")

    @pytest.mark.asyncio
    async def test_idle_countdown_fires_pause(self) -> None:
        """_idle_countdown pauses the workspace after timeout elapses."""
        mgr = WorkspaceManager(auto_pause=True, pause_timeout=0)

        # Inject a fake active workspace
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
    async def test_idle_countdown_skips_non_active(self) -> None:
        """_idle_countdown does nothing if workspace is not ACTIVE."""
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
    async def test_idle_timer_not_created_when_auto_pause_off(self) -> None:
        """No idle timer when auto_pause=False."""
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
    async def test_no_global_scan_task(self) -> None:
        """WorkspaceManager no longer uses a global 60s scan task."""
        mgr = await WorkspaceManager.create(auto_pause=True)
        # The old _pause_task attribute is gone
        assert not hasattr(mgr, "_pause_task")
        await mgr.shutdown_all()

    @pytest.mark.asyncio
    async def test_destroy_cancels_idle_timer(self) -> None:
        """Destroying a workspace cancels its idle timer."""
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

    @pytest.mark.asyncio
    async def test_active_turn_counter_prevents_premature_timer(self) -> None:
        """Idle timer does not restart while another conversation's turn is active."""
        mgr = WorkspaceManager(auto_pause=True, pause_timeout=9999)

        # Simulate two concurrent turns in flight for the same workspace
        mgr._active_turns["w-1"] = 2

        # After one turn ends, counter drops to 1 — no timer yet
        count = max(0, mgr._active_turns.get("w-1", 1) - 1)
        mgr._active_turns["w-1"] = count
        assert "w-1" not in mgr._idle_timers

    @pytest.mark.asyncio
    async def test_idle_timer_starts_when_last_turn_ends(self) -> None:
        """Idle timer starts once the last active turn completes."""
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
    async def test_turn_ended_seen_prevents_double_decrement(self) -> None:
        """finally block does NOT decrement when TURN_ENDED already fired.

        Regression test for the concurrent-turn double-decrement bug:
        with two turns in flight, the first turn's TURN_ENDED decrements 2→1,
        then the finally block used to see active>0 and decrement again to 0,
        prematurely starting the idle timer while agent B is still running.
        """
        mgr = WorkspaceManager(auto_pause=True, pause_timeout=9999)
        # Start with 2 concurrent turns
        mgr._active_turns["w-1"] = 2

        # Simulate TURN_ENDED for turn A: decrement 2→1
        active = max(0, mgr._active_turns.get("w-1", 1) - 1)
        mgr._active_turns["w-1"] = active
        turn_ended_seen = True  # Set by the TURN_ENDED handler

        # Now the finally block runs — with the fix, it checks turn_ended_seen
        if not turn_ended_seen:
            active = max(0, mgr._active_turns.get("w-1", 1) - 1)
            mgr._active_turns["w-1"] = active
            if active == 0 and mgr._auto_pause:
                mgr._start_idle_timer("w-1")

        # Counter should still be 1 (agent B still running), timer not started
        assert mgr._active_turns["w-1"] == 1
        assert "w-1" not in mgr._idle_timers


# ---------------------------------------------------------------------------
# Part B: E2B proactive timeout extension
# ---------------------------------------------------------------------------


class TestE2BTimeoutExtension:
    """E2B provider extends sandbox timeout when a turn runs past the halfway mark."""

    def _make_provider(self, timeout: int = 300) -> object:
        from harnessbox._providers.e2b import E2BProvider

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

    @pytest.mark.asyncio
    async def test_no_extension_before_halfway(self) -> None:
        from harnessbox._providers.e2b import E2BProvider

        p = self._make_provider(timeout=300)
        assert isinstance(p, E2BProvider)
        p.notify_turn_start()
        # Artificially set start time to 10s ago (well before 150s halfway mark)
        p._turn_start_time = time.monotonic() - 10
        extended = await p.maybe_extend_timeout()
        assert not extended
        p._sandbox.set_timeout.assert_not_called()

    @pytest.mark.asyncio
    async def test_extension_after_halfway(self) -> None:
        from harnessbox._providers.e2b import E2BProvider

        p = self._make_provider(timeout=300)
        assert isinstance(p, E2BProvider)
        p.notify_turn_start()
        # 160s elapsed > 150s halfway; remaining = max(0, 300 - 160) = 140
        p._turn_start_time = time.monotonic() - 160
        extended = await p.maybe_extend_timeout()
        assert extended
        # set_timeout receives remaining + extension = 140 + 150 = 290
        call_arg = p._sandbox.set_timeout.call_args[0][0]
        assert 280 <= call_arg <= 300  # allow ±10s for timing jitter
        assert p._total_extensions == 150

    @pytest.mark.asyncio
    async def test_extension_cap_not_exceeded(self) -> None:
        """Total extensions cannot exceed (MAX_EXTENSION_MULTIPLIER - 1) * timeout."""
        from harnessbox._providers.e2b import E2BProvider

        p = self._make_provider(timeout=300)
        assert isinstance(p, E2BProvider)
        max_extra = (p._MAX_EXTENSION_MULTIPLIER - 1) * 300  # 600
        p._total_extensions = max_extra
        p._turn_start_time = time.monotonic() - 200
        extended = await p.maybe_extend_timeout()
        assert not extended

    @pytest.mark.asyncio
    async def test_extension_capped_at_remaining_budget(self) -> None:
        """Extension is reduced to the remaining budget if less than half timeout."""
        from harnessbox._providers.e2b import E2BProvider

        p = self._make_provider(timeout=300)
        assert isinstance(p, E2BProvider)
        # Only 50s of budget left; elapsed=200 so remaining = max(0, 300-200) = 100
        p._total_extensions = 550  # max_extra=600, so 50 remaining budget
        p._turn_start_time = time.monotonic() - 200
        extended = await p.maybe_extend_timeout()
        assert extended
        # set_timeout receives remaining + capped_extension = 100 + 50 = 150
        call_arg = p._sandbox.set_timeout.call_args[0][0]
        assert 140 <= call_arg <= 160  # allow ±10s for timing jitter

    @pytest.mark.asyncio
    async def test_no_extension_when_no_turn(self) -> None:
        """No extension if notify_turn_start was never called."""
        from harnessbox._providers.e2b import E2BProvider

        p = self._make_provider(timeout=300)
        assert isinstance(p, E2BProvider)
        # _turn_start_time is None
        extended = await p.maybe_extend_timeout()
        assert not extended

    @pytest.mark.asyncio
    async def test_notify_turn_end_clears_start_time(self) -> None:
        from harnessbox._providers.e2b import E2BProvider

        p = self._make_provider(timeout=300)
        assert isinstance(p, E2BProvider)
        p.notify_turn_start()
        assert p._turn_start_time is not None
        p.notify_turn_end()
        assert p._turn_start_time is None

    @pytest.mark.asyncio
    async def test_at_most_one_extension_per_turn(self) -> None:
        """maybe_extend_timeout fires set_timeout exactly once per turn, no matter how
        many events are yielded after the halfway mark."""
        from harnessbox._providers.e2b import E2BProvider

        p = self._make_provider(timeout=300)
        assert isinstance(p, E2BProvider)
        p._turn_start_time = time.monotonic() - 200
        first = await p.maybe_extend_timeout()
        second = await p.maybe_extend_timeout()
        third = await p.maybe_extend_timeout()
        assert first is True
        assert second is False
        assert third is False
        p._sandbox.set_timeout.assert_called_once()

        # After notify_turn_end + notify_turn_start, the flag resets and we can extend again
        p.notify_turn_end()
        p.notify_turn_start()
        p._turn_start_time = time.monotonic() - 200
        assert await p.maybe_extend_timeout() is True

    @pytest.mark.asyncio
    async def test_extension_fails_gracefully(self) -> None:
        """Failed set_timeout call returns False without raising."""
        from harnessbox._providers.e2b import E2BProvider

        p = self._make_provider(timeout=300)
        assert isinstance(p, E2BProvider)
        p._sandbox.set_timeout = AsyncMock(side_effect=Exception("network error"))
        p._turn_start_time = time.monotonic() - 200
        extended = await p.maybe_extend_timeout()
        assert not extended

    @pytest.mark.asyncio
    async def test_create_resets_extension_counters(self) -> None:
        """create() resets _total_extensions and _extended_this_turn for the new sandbox."""
        from harnessbox._providers.e2b import E2BProvider

        p = self._make_provider(timeout=300)
        assert isinstance(p, E2BProvider)
        # Simulate an old sandbox that used its full extension budget
        p._total_extensions = 600
        p._extended_this_turn = True

        # Patch the SDK import so create() doesn't need a real e2b package
        mock_sandbox = MagicMock()
        mock_sandbox.sandbox_id = "sb-new"
        mock_cls = AsyncMock(return_value=mock_sandbox)

        with patch.object(p, "_get_sdk", return_value=mock_cls):
            await p.create(timeout=300)

        assert p._total_extensions == 0
        assert p._extended_this_turn is False


# ---------------------------------------------------------------------------
# Part C: Snapshot recovery
# ---------------------------------------------------------------------------


class TestSnapshotRecovery:
    """_resume_workspace recovers from expired/killed sandboxes via snapshot."""

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
    async def test_recovery_creates_new_sandbox_from_snapshot(self) -> None:
        """When sandbox is expired, create() is called with the snapshot_id."""
        from harnessbox.providers import SandboxDeadError

        mgr, info, provider = self._make_mgr_with_workspace()

        # provider.create with snapshot_id should succeed and set a new sandbox_id
        created_calls: list[dict[str, object]] = []

        async def fake_create(
            env_vars: dict[str, str] | None = None,
            timeout: int = 300,
            snapshot_id: str | None = None,
        ) -> None:
            created_calls.append(
                {"env_vars": env_vars, "timeout": timeout, "snapshot_id": snapshot_id}
            )
            provider._sandbox_id = "sb-new"
            provider._running = True

        provider.create = fake_create  # type: ignore[method-assign]

        # Patch _try_resume_sandbox to raise SandboxDeadError
        failing = AsyncMock(side_effect=SandboxDeadError("sandbox was not found"))
        with patch.object(mgr, "_try_resume_sandbox", failing):
            await mgr._resume_workspace("w-1")

        assert len(created_calls) == 1
        assert created_calls[0]["snapshot_id"] == "snap-1"
        assert info.runtime_state == RuntimeState.ACTIVE.value
        assert info.provider_sandbox_id == "sb-new"

    @pytest.mark.asyncio
    async def test_recovery_raises_when_no_snapshot(self) -> None:
        """Raises ValueError when sandbox expired and no snapshot available."""
        from harnessbox.providers import SandboxDeadError

        mgr, info, provider = self._make_mgr_with_workspace(snapshot_id=None)

        failing = AsyncMock(side_effect=SandboxDeadError("sandbox was not found"))
        with patch.object(mgr, "_try_resume_sandbox", failing):
            with pytest.raises(ValueError, match="has no snapshot"):
                await mgr._resume_workspace("w-1")

    @pytest.mark.asyncio
    async def test_recovery_raises_when_snapshot_expired(self) -> None:
        """Raises ValueError with clear message when snapshot itself is gone."""
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
        """Normal resume (no expiry) transitions to ACTIVE without snapshot recovery."""
        mgr, info, provider = self._make_mgr_with_workspace()

        provider._sandbox_id = "sb-old"
        provider._running = True

        ok = AsyncMock()
        with patch.object(mgr, "_try_resume_sandbox", ok):
            await mgr._resume_workspace("w-1")

        assert info.runtime_state == RuntimeState.ACTIVE.value

    @pytest.mark.asyncio
    async def test_recovery_updates_storage(self) -> None:
        """After snapshot recovery, the new sandbox_id is persisted to storage."""
        from harnessbox._storage.memory import MemoryBackend
        from harnessbox.providers import SandboxDeadError

        storage = MemoryBackend()
        await storage.initialize()

        mgr, info, provider = self._make_mgr_with_workspace()
        mgr._storage = storage

        # Persist the old workspace record
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

        # Verify new sandbox_id was persisted
        records = await storage.list_workspaces()
        assert records[0]["provider_sandbox_id"] == "sb-new"
