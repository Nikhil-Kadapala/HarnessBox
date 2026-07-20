"""Tests for harnessbox.agent_manager — AgentManager lazy agent spawning."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from harnessbox._server.agent_manager import AgentManager
from harnessbox.streaming import EventType, UniversalEvent


async def _async_gen_from(items):
    """Helper: create an async generator yielding items."""
    for item in items:
        yield item


def _make_event(
    session_id: str = "",
    event_type: EventType = EventType.ITEM_DELTA,
    sequence: int = 1,
) -> UniversalEvent:
    return UniversalEvent(
        event_id=f"evt-{sequence}",
        sequence=sequence,
        timestamp="2026-05-26T20:00:00Z",
        session_id=session_id,
        event_type=event_type,
    )


@pytest.fixture
def mock_sandbox():
    """Mock sandbox with required attributes."""
    sandbox = MagicMock()
    sandbox._provider = MagicMock()
    sandbox._skip_permissions = False
    sandbox._cwd = "/workspace"
    sandbox.event_buffer = MagicMock()
    sandbox.event_buffer.push = AsyncMock(side_effect=lambda e: e)
    return sandbox


class TestAgentManagerLazySpawn:
    """Test lazy agent spawning on first prompt."""

    @pytest.mark.asyncio
    async def test_spawns_agent_on_first_prompt(self, mock_sandbox):
        """Should spawn agent process when conversation_id is new."""
        mgr = AgentManager(mock_sandbox)

        with (
            patch("harnessbox._server.agent_manager.AgentProcess") as MockAgentProcess,
            patch("harnessbox._server.agent_manager.get_harness_type"),
        ):
            mock_process = MockAgentProcess.return_value
            mock_process.start = AsyncMock()
            mock_process.send_prompt = AsyncMock()
            mock_process.stream_turn = lambda: _async_gen_from(
                [_make_event(session_id="conv-1", sequence=1)]
            )

            events = []
            async for event in mgr.send_message("conv-1", "hello"):
                events.append(event)
                break

        assert "conv-1" in mgr._agents
        mock_process.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_reuses_agent_on_second_prompt(self, mock_sandbox):
        """Should reuse existing agent for same conversation_id."""
        mgr = AgentManager(mock_sandbox)

        with (
            patch("harnessbox._server.agent_manager.AgentProcess") as MockAgentProcess,
            patch("harnessbox._server.agent_manager.get_harness_type"),
        ):
            mock_process = MockAgentProcess.return_value
            mock_process.start = AsyncMock()
            mock_process.send_prompt = AsyncMock()
            mock_process.stream_turn = lambda: _async_gen_from(
                [_make_event(session_id="conv-1", sequence=1)]
            )

            async for _ in mgr.send_message("conv-1", "hello"):
                break

            async for _ in mgr.send_message("conv-1", "world"):
                break

        assert mock_process.start.call_count == 1
        assert mock_process.send_prompt.call_count == 2


class TestAgentManagerConcurrent:
    """Test concurrent agents (multiple conversation_ids)."""

    @pytest.mark.asyncio
    async def test_multiple_conversations_multiple_agents(self, mock_sandbox):
        """Should spawn separate agent for each conversation_id."""
        mgr = AgentManager(mock_sandbox)

        with (
            patch("harnessbox._server.agent_manager.AgentProcess") as MockAgentProcess,
            patch("harnessbox._server.agent_manager.get_harness_type"),
        ):
            mock_process1 = MagicMock()
            mock_process1.start = AsyncMock()
            mock_process1.send_prompt = AsyncMock()
            mock_process1.stream_turn = lambda: _async_gen_from(
                [_make_event(session_id="conv-1", sequence=1)]
            )

            mock_process2 = MagicMock()
            mock_process2.start = AsyncMock()
            mock_process2.send_prompt = AsyncMock()
            mock_process2.stream_turn = lambda: _async_gen_from(
                [_make_event(session_id="conv-2", sequence=1)]
            )

            MockAgentProcess.side_effect = [mock_process1, mock_process2]

            async for _ in mgr.send_message("conv-1", "hello"):
                break
            async for _ in mgr.send_message("conv-2", "world"):
                break

        assert len(mgr._agents) == 2
        assert "conv-1" in mgr._agents
        assert "conv-2" in mgr._agents


class TestAgentManagerTermination:
    """Test agent termination."""

    @pytest.mark.asyncio
    async def test_terminate_agent(self, mock_sandbox):
        """Should stop and remove agent process."""
        mgr = AgentManager(mock_sandbox)

        with (
            patch("harnessbox._server.agent_manager.AgentProcess") as MockAgentProcess,
            patch("harnessbox._server.agent_manager.get_harness_type"),
        ):
            mock_process = MockAgentProcess.return_value
            mock_process.start = AsyncMock()
            mock_process.send_prompt = AsyncMock()
            mock_process.stop = AsyncMock()
            mock_process.stream_turn = lambda: _async_gen_from(
                [_make_event(session_id="conv-1", sequence=1)]
            )

            async for _ in mgr.send_message("conv-1", "hello"):
                break

            await mgr.terminate_agent("conv-1")

        assert "conv-1" not in mgr._agents
        mock_process.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_all(self, mock_sandbox):
        """Should terminate all agents."""
        mgr = AgentManager(mock_sandbox)

        with (
            patch("harnessbox._server.agent_manager.AgentProcess") as MockAgentProcess,
            patch("harnessbox._server.agent_manager.get_harness_type"),
        ):
            mock_process1 = MagicMock()
            mock_process1.start = AsyncMock()
            mock_process1.send_prompt = AsyncMock()
            mock_process1.stop = AsyncMock()
            mock_process1.stream_turn = lambda: _async_gen_from(
                [_make_event(session_id="conv-1", sequence=1)]
            )

            mock_process2 = MagicMock()
            mock_process2.start = AsyncMock()
            mock_process2.send_prompt = AsyncMock()
            mock_process2.stop = AsyncMock()
            mock_process2.stream_turn = lambda: _async_gen_from(
                [_make_event(session_id="conv-2", sequence=1)]
            )

            MockAgentProcess.side_effect = [mock_process1, mock_process2]

            async for _ in mgr.send_message("conv-1", "hello"):
                break
            async for _ in mgr.send_message("conv-2", "world"):
                break

            await mgr.shutdown_all()

        assert len(mgr._agents) == 0
        mock_process1.stop.assert_called_once()
        mock_process2.stop.assert_called_once()


class TestAgentManagerReattachAll:
    """Regression: sandbox resume must re-attach every tracked process's
    stdout stream, not just leave orphaned processes hanging on the next turn."""

    @pytest.mark.asyncio
    async def test_reattaches_every_tracked_process(self, mock_sandbox):
        mgr = AgentManager(mock_sandbox)
        mgr._agents = {
            "conv-1": (p1 := MagicMock(reattach=AsyncMock())),
            "conv-2": (p2 := MagicMock(reattach=AsyncMock())),
        }

        await mgr.reattach_all()

        p1.reattach.assert_called_once()
        p2.reattach.assert_called_once()
        assert set(mgr._agents) == {"conv-1", "conv-2"}

    @pytest.mark.asyncio
    async def test_failed_reattach_drops_the_conversation(self, mock_sandbox):
        """A process that can't be reattached (e.g. it no longer exists) is
        dropped so the next send_message respawns it fresh via --resume."""
        mgr = AgentManager(mock_sandbox)
        ok_process = MagicMock(reattach=AsyncMock())
        dead_process = MagicMock(reattach=AsyncMock(side_effect=RuntimeError("gone")))
        mgr._agents = {"conv-ok": ok_process, "conv-dead": dead_process}
        mgr._locks = {"conv-ok": object(), "conv-dead": object()}

        await mgr.reattach_all()

        assert "conv-ok" in mgr._agents
        assert "conv-dead" not in mgr._agents
        assert "conv-dead" not in mgr._locks


class TestAgentManagerConversationList:
    """Test conversation listing."""

    def test_list_conversations(self, mock_sandbox):
        """Should return list of active conversation IDs."""
        mgr = AgentManager(mock_sandbox)
        mgr._agents = {"conv-1": MagicMock(), "conv-2": MagicMock()}

        result = mgr.list_conversations()

        assert set(result) == {"conv-1", "conv-2"}


class TestAgentManagerSessionIdStamping:
    """Regression: events must always carry conversation_id as session_id."""

    @pytest.mark.asyncio
    async def test_events_stamped_with_conversation_id(self, mock_sandbox):
        """Claude emits its own internal UUID as session_id. The agent manager
        must override it with conversation_id so the frontend can filter events
        correctly. Claude's UUID is preserved in metadata._agent_session_id."""
        mgr = AgentManager(mock_sandbox)

        claude_internal_sid = "9b444125-internal-uuid"
        conversation_id = "401ac3bc-user-conversation"

        with (
            patch("harnessbox._server.agent_manager.AgentProcess") as MockAgentProcess,
            patch("harnessbox._server.agent_manager.get_harness_type"),
        ):
            mock_process = MockAgentProcess.return_value
            mock_process.start = AsyncMock()
            mock_process.send_prompt = AsyncMock()
            mock_process.stream_turn = lambda: _async_gen_from(
                [
                    _make_event(session_id=claude_internal_sid, sequence=1),
                    _make_event(session_id=claude_internal_sid, sequence=2),
                    _make_event(session_id="", sequence=3),
                ]
            )
            mock_process.poll_status = AsyncMock(return_value=[])

            events = []
            async for event in mgr.send_message(conversation_id, "hello"):
                events.append(event)

        assert len(events) == 3
        for event in events:
            assert event.session_id == conversation_id
            assert event.metadata["_agent_session_id"] == claude_internal_sid

    @pytest.mark.asyncio
    async def test_events_with_no_agent_session_id(self, mock_sandbox):
        """When Claude provides no session_id at all, events still get
        conversation_id and metadata._agent_session_id stays absent."""
        mgr = AgentManager(mock_sandbox)

        conversation_id = "conv-no-session"

        with (
            patch("harnessbox._server.agent_manager.AgentProcess") as MockAgentProcess,
            patch("harnessbox._server.agent_manager.get_harness_type"),
        ):
            mock_process = MockAgentProcess.return_value
            mock_process.start = AsyncMock()
            mock_process.send_prompt = AsyncMock()
            mock_process.stream_turn = lambda: _async_gen_from(
                [_make_event(session_id="", sequence=1)]
            )
            mock_process.poll_status = AsyncMock(return_value=[])

            events = []
            async for event in mgr.send_message(conversation_id, "hello"):
                events.append(event)

        assert len(events) == 1
        assert events[0].session_id == conversation_id
        assert "_agent_session_id" not in events[0].metadata


class TestAgentManagerPerConversationHarness:
    """Per-conversation harness: different conversations can use different agents."""

    @pytest.mark.asyncio
    async def test_multi_harness_same_session(self, mock_sandbox):
        """Two conversations with different harnesses spawn different processes."""
        mgr = AgentManager(mock_sandbox)

        with (
            patch("harnessbox._server.agent_manager.AgentProcess") as MockAgentProcess,
            patch("harnessbox._server.agent_manager.get_harness_type") as mock_get_harness,
        ):
            mock_process1 = MagicMock()
            mock_process1.start = AsyncMock()
            mock_process1.send_prompt = AsyncMock()
            mock_process1.stream_turn = lambda: _async_gen_from(
                [_make_event(session_id="claude-sid", sequence=1)]
            )
            mock_process1.poll_status = AsyncMock(return_value=[])

            mock_process2 = MagicMock()
            mock_process2.start = AsyncMock()
            mock_process2.send_prompt = AsyncMock()
            mock_process2.stream_turn = lambda: _async_gen_from(
                [_make_event(session_id="codex-sid", sequence=1)]
            )
            mock_process2.poll_status = AsyncMock(return_value=[])

            MockAgentProcess.side_effect = [mock_process1, mock_process2]
            mock_harness_config = MagicMock()
            mock_harness_config.build_session_command.return_value = ["claude"]
            mock_get_harness.return_value = mock_harness_config

            async for _ in mgr.send_message("conv-claude", "hello", "claude-code"):
                pass
            async for _ in mgr.send_message("conv-codex", "hello", "codex"):
                pass

        assert len(mgr._agents) == 2
        assert "conv-claude" in mgr._agents
        assert "conv-codex" in mgr._agents
        assert mock_get_harness.call_count == 2
        harness_calls = [c.args[0] for c in mock_get_harness.call_args_list]
        assert harness_calls == ["claude-code", "codex"]

    @pytest.mark.asyncio
    async def test_harness_passed_to_spawn(self, mock_sandbox):
        """The harness param reaches _spawn_agent and get_harness_type."""
        mgr = AgentManager(mock_sandbox)

        with (
            patch("harnessbox._server.agent_manager.AgentProcess") as MockAgentProcess,
            patch("harnessbox._server.agent_manager.get_harness_type") as mock_get_harness,
        ):
            mock_process = MockAgentProcess.return_value
            mock_process.start = AsyncMock()
            mock_process.send_prompt = AsyncMock()
            mock_process.stream_turn = lambda: _async_gen_from(
                [_make_event(session_id="sid", sequence=1)]
            )
            mock_process.poll_status = AsyncMock(return_value=[])

            mock_harness_config = MagicMock()
            mock_harness_config.build_session_command.return_value = ["opencode"]
            mock_get_harness.return_value = mock_harness_config

            async for _ in mgr.send_message("conv-1", "hello", "opencode"):
                pass

        mock_get_harness.assert_called_once_with("opencode")
