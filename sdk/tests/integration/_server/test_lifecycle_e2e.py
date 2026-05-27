"""End-to-end integration tests for the workspace lifecycle cycle.

Exercises the full flow at the WorkspaceManager level:
  create → prompt → idle timer fires → auto-pause → prompt → auto-resume → response

Uses MockProvider and MemoryBackend to verify real async timer machinery,
state transitions, event emission, and storage persistence without hitting E2B.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from harnessbox._server._storage.memory import MemoryBackend
from harnessbox.lifecycle import RuntimeState
from harnessbox.streaming import EventType, UniversalEvent
from harnessbox._server.workspace_manager import WorkspaceConfig, WorkspaceManager


def _make_turn_event(session_id: str, event_type: EventType, **kwargs: Any) -> UniversalEvent:
    return UniversalEvent(
        event_id="ev-test",
        sequence=0,
        timestamp=datetime.now(timezone.utc).isoformat(),
        session_id=session_id,
        event_type=event_type,
        **kwargs,
    )


class TestLifecycleE2E:
    """Full lifecycle: create → prompt → idle → pause → prompt → resume → response."""

    @pytest.mark.asyncio
    async def test_full_idle_pause_resume_cycle(self) -> None:
        """Workspace auto-pauses after idle timeout, then auto-resumes on next prompt."""
        storage = MemoryBackend()
        await storage.initialize()

        # Use a very short pause_timeout so the idle timer fires quickly
        mgr = await WorkspaceManager.create(storage=storage, auto_pause=True, pause_timeout=0)

        # --- Phase 1: Create workspace ---
        with (
            patch("harnessbox._server.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox._server.workspace_manager.AgentManager") as MockAgentMgr,
        ):
            sandbox_instance = MockSandbox.return_value
            sandbox_instance.setup = AsyncMock()
            sandbox_instance.sandbox_id = "sb-lifecycle"
            sandbox_instance._cwd = "/workspace"
            sandbox_instance._event_buffer = MagicMock()
            sandbox_instance._event_buffer.push = AsyncMock(side_effect=lambda e: e)
            sandbox_instance._event_buffer.close = AsyncMock()
            sandbox_instance.create_snapshot = AsyncMock(return_value="snap-lifecycle")
            sandbox_instance.pause = AsyncMock(return_value="sb-lifecycle")
            sandbox_instance.resume = AsyncMock()
            sandbox_instance.event_buffer = sandbox_instance._event_buffer

            # Agent: yields a TURN_ENDED event on each prompt
            turn_count = [0]

            async def mock_send_message(
                conv_id: str, prompt: str, harness: str = "claude-code", **kwargs: Any
            ):
                turn_count[0] += 1
                yield _make_turn_event(
                    conv_id,
                    EventType.ITEM_DELTA,
                    delta=f"Response {turn_count[0]}",
                )
                yield _make_turn_event(conv_id, EventType.TURN_ENDED, duration_ms=100)

            agent_instance = MockAgentMgr.return_value
            agent_instance.send_message = mock_send_message
            agent_instance.shutdown_all = AsyncMock()

            config = WorkspaceConfig(provider="e2b", harness="claude-code")
            info = await mgr.create_workspace(config, workspace_id="w-e2e")

        assert info.runtime_state == RuntimeState.ACTIVE.value
        assert "w-e2e" in mgr._idle_timers

        # --- Phase 2: Send first prompt (should cancel + restart idle timer) ---
        events_1: list[UniversalEvent] = []
        async for event in mgr.prompt("w-e2e", "Hello"):
            events_1.append(event)

        # Should have USER_PROMPT + ITEM_DELTA + TURN_ENDED
        event_types_1 = [e.event_type for e in events_1]
        assert EventType.USER_PROMPT in event_types_1
        assert EventType.TURN_ENDED in event_types_1
        assert info.runtime_state == RuntimeState.ACTIVE.value

        # --- Phase 3: Let idle timer fire (pause_timeout=0, so it fires immediately) ---
        # The timer was restarted after TURN_ENDED. Give it a tick to fire.
        await asyncio.sleep(0.05)

        # Verify auto-pause happened
        assert info.runtime_state == RuntimeState.PAUSED.value
        assert info.snapshot_id == "snap-lifecycle"
        sandbox_instance.create_snapshot.assert_called()
        sandbox_instance.pause.assert_called()

        # --- Phase 4: Send second prompt (should auto-resume then respond) ---
        events_2: list[UniversalEvent] = []
        async for event in mgr.prompt("w-e2e", "After resume"):
            events_2.append(event)

        # Should have auto-resumed
        assert info.runtime_state == RuntimeState.ACTIVE.value
        sandbox_instance.resume.assert_called_with("sb-lifecycle")

        # Should get a fresh response
        event_types_2 = [e.event_type for e in events_2]
        assert EventType.USER_PROMPT in event_types_2
        assert EventType.TURN_ENDED in event_types_2
        assert turn_count[0] == 2

        # Cleanup
        mgr._cancel_idle_timer("w-e2e")

    @pytest.mark.asyncio
    async def test_idle_timer_cancelled_during_turn(self) -> None:
        """Idle timer should not fire while a turn is in flight."""
        storage = MemoryBackend()
        await storage.initialize()

        mgr = await WorkspaceManager.create(storage=storage, auto_pause=True, pause_timeout=0)

        with (
            patch("harnessbox._server.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox._server.workspace_manager.AgentManager") as MockAgentMgr,
        ):
            sandbox_instance = MockSandbox.return_value
            sandbox_instance.setup = AsyncMock()
            sandbox_instance.sandbox_id = "sb-busy"
            sandbox_instance._cwd = "/workspace"
            sandbox_instance._event_buffer = MagicMock()
            sandbox_instance._event_buffer.push = AsyncMock(side_effect=lambda e: e)
            sandbox_instance._event_buffer.close = AsyncMock()
            sandbox_instance.create_snapshot = AsyncMock(return_value="snap-busy")
            sandbox_instance.pause = AsyncMock(return_value="sb-busy")
            sandbox_instance.event_buffer = sandbox_instance._event_buffer

            # Agent takes a while to respond (simulates a long turn)
            async def slow_send_message(
                conv_id: str, prompt: str, harness: str = "claude-code", **kwargs: Any
            ):
                await asyncio.sleep(0.1)  # Simulate processing
                yield _make_turn_event(conv_id, EventType.TURN_ENDED, duration_ms=500)

            agent_instance = MockAgentMgr.return_value
            agent_instance.send_message = slow_send_message
            agent_instance.shutdown_all = AsyncMock()

            config = WorkspaceConfig(provider="e2b", harness="claude-code")
            info = await mgr.create_workspace(config, workspace_id="w-busy")

        # Send prompt — idle timer was cancelled at turn start
        events: list[UniversalEvent] = []
        async for event in mgr.prompt("w-busy", "Do something slow"):
            events.append(event)

        # During the turn the workspace should NOT have been paused
        assert info.runtime_state == RuntimeState.ACTIVE.value
        assert EventType.TURN_ENDED in [e.event_type for e in events]

        # Now let idle timer fire AFTER turn completes
        await asyncio.sleep(0.05)
        assert info.runtime_state == RuntimeState.PAUSED.value

        mgr._cancel_idle_timer("w-busy")

    @pytest.mark.asyncio
    async def test_runtime_state_event_emitted_on_pause_and_resume(self) -> None:
        """runtime.state events should be emitted to the event buffer on transitions."""
        storage = MemoryBackend()
        await storage.initialize()

        mgr = await WorkspaceManager.create(storage=storage, auto_pause=True, pause_timeout=0)

        pushed_events: list[UniversalEvent] = []

        async def capture_push(event: UniversalEvent) -> UniversalEvent:
            pushed_events.append(event)
            return event

        with (
            patch("harnessbox._server.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox._server.workspace_manager.AgentManager") as MockAgentMgr,
        ):
            sandbox_instance = MockSandbox.return_value
            sandbox_instance.setup = AsyncMock()
            sandbox_instance.sandbox_id = "sb-events"
            sandbox_instance._cwd = "/workspace"
            sandbox_instance._event_buffer = MagicMock()
            sandbox_instance._event_buffer.push = AsyncMock(side_effect=capture_push)
            sandbox_instance._event_buffer.close = AsyncMock()
            sandbox_instance.create_snapshot = AsyncMock(return_value="snap-events")
            sandbox_instance.pause = AsyncMock(return_value="sb-events")
            sandbox_instance.resume = AsyncMock()
            sandbox_instance.event_buffer = sandbox_instance._event_buffer

            async def mock_send_message(
                conv_id: str, prompt: str, harness: str = "claude-code", **kwargs: Any
            ):
                yield _make_turn_event(conv_id, EventType.TURN_ENDED, duration_ms=50)

            agent_instance = MockAgentMgr.return_value
            agent_instance.send_message = mock_send_message
            agent_instance.shutdown_all = AsyncMock()

            config = WorkspaceConfig(provider="e2b", harness="claude-code")
            info = await mgr.create_workspace(config, workspace_id="w-events")

        # Send prompt so idle timer restarts after TURN_ENDED
        async for _ in mgr.prompt("w-events", "trigger"):
            pass

        # Let idle timer fire → should emit runtime.state=paused
        await asyncio.sleep(0.05)
        assert info.runtime_state == RuntimeState.PAUSED.value

        # Find the runtime.state event for pause
        pause_events = [
            e
            for e in pushed_events
            if e.event_type == EventType.RUNTIME_STATE
            and e.metadata.get("runtime_state") == RuntimeState.PAUSED.value
        ]
        assert len(pause_events) >= 1

        # Resume and check active event
        pushed_events.clear()
        async for _ in mgr.prompt("w-events", "after resume"):
            pass

        assert info.runtime_state == RuntimeState.ACTIVE.value

        active_events = [
            e
            for e in pushed_events
            if e.event_type == EventType.RUNTIME_STATE
            and e.metadata.get("runtime_state") == RuntimeState.ACTIVE.value
        ]
        assert len(active_events) >= 1

        mgr._cancel_idle_timer("w-events")

    @pytest.mark.asyncio
    async def test_storage_persists_state_across_pause_resume(self) -> None:
        """Storage should reflect runtime_state transitions and snapshot_id."""
        storage = MemoryBackend()
        await storage.initialize()

        mgr = await WorkspaceManager.create(storage=storage, auto_pause=True, pause_timeout=0)

        with (
            patch("harnessbox._server.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox._server.workspace_manager.AgentManager") as MockAgentMgr,
        ):
            sandbox_instance = MockSandbox.return_value
            sandbox_instance.setup = AsyncMock()
            sandbox_instance.sandbox_id = "sb-persist"
            sandbox_instance._cwd = "/workspace"
            sandbox_instance._event_buffer = MagicMock()
            sandbox_instance._event_buffer.push = AsyncMock(side_effect=lambda e: e)
            sandbox_instance._event_buffer.close = AsyncMock()
            sandbox_instance.create_snapshot = AsyncMock(return_value="snap-persist")
            sandbox_instance.pause = AsyncMock(return_value="sb-persist")
            sandbox_instance.resume = AsyncMock()
            sandbox_instance.event_buffer = sandbox_instance._event_buffer

            async def mock_send_message(
                conv_id: str, prompt: str, harness: str = "claude-code", **kwargs: Any
            ):
                yield _make_turn_event(conv_id, EventType.TURN_ENDED, duration_ms=50)

            agent_instance = MockAgentMgr.return_value
            agent_instance.send_message = mock_send_message
            agent_instance.shutdown_all = AsyncMock()

            config = WorkspaceConfig(provider="e2b", harness="claude-code")
            await mgr.create_workspace(config, workspace_id="w-persist")

        # Trigger prompt then idle-pause
        async for _ in mgr.prompt("w-persist", "first"):
            pass
        await asyncio.sleep(0.05)

        # Verify storage shows paused + snapshot
        records = await storage.list_workspaces()
        record = next(r for r in records if r["workspace_id"] == "w-persist")
        assert record["runtime_state"] == RuntimeState.PAUSED.value
        assert record["snapshot_id"] == "snap-persist"

        # Resume via prompt
        async for _ in mgr.prompt("w-persist", "second"):
            pass

        # Verify storage shows active again
        records = await storage.list_workspaces()
        record = next(r for r in records if r["workspace_id"] == "w-persist")
        assert record["runtime_state"] == RuntimeState.ACTIVE.value

        mgr._cancel_idle_timer("w-persist")

    @pytest.mark.asyncio
    async def test_graceful_shutdown_pauses_active_with_timer(self) -> None:
        """Server shutdown pauses active workspaces regardless of idle timer state."""
        storage = MemoryBackend()
        await storage.initialize()

        mgr = await WorkspaceManager.create(storage=storage, auto_pause=True, pause_timeout=9999)

        with (
            patch("harnessbox._server.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox._server.workspace_manager.AgentManager") as MockAgentMgr,
        ):
            sandbox_instance = MockSandbox.return_value
            sandbox_instance.setup = AsyncMock()
            sandbox_instance.sandbox_id = "sb-shutdown"
            sandbox_instance._cwd = "/workspace"
            sandbox_instance._event_buffer = MagicMock()
            sandbox_instance._event_buffer.push = AsyncMock(side_effect=lambda e: e)
            sandbox_instance._event_buffer.close = AsyncMock()
            sandbox_instance.create_snapshot = AsyncMock(return_value="snap-shutdown")
            sandbox_instance.pause = AsyncMock(return_value="sb-shutdown")
            sandbox_instance.event_buffer = sandbox_instance._event_buffer

            async def mock_send_message(
                conv_id: str, prompt: str, harness: str = "claude-code", **kwargs: Any
            ):
                yield _make_turn_event(conv_id, EventType.TURN_ENDED, duration_ms=50)

            agent_instance = MockAgentMgr.return_value
            agent_instance.send_message = mock_send_message
            agent_instance.shutdown_all = AsyncMock()

            config = WorkspaceConfig(provider="e2b", harness="claude-code")
            info = await mgr.create_workspace(config, workspace_id="w-shutdown")

        # Send a prompt to make it active
        async for _ in mgr.prompt("w-shutdown", "working"):
            pass

        assert info.runtime_state == RuntimeState.ACTIVE.value
        assert "w-shutdown" in mgr._idle_timers

        # Simulate server shutdown
        await mgr.graceful_shutdown()

        assert info.runtime_state == RuntimeState.PAUSED.value
        assert info.snapshot_id == "snap-shutdown"
        # Idle timers should be cleaned up
        assert "w-shutdown" not in mgr._idle_timers
