"""Tests for harnessbox.agent_manager — AgentManager lazy agent spawning."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from harnessbox.agent_manager import AgentManager


async def _async_gen_from(items):
    """Helper: create an async generator yielding items."""
    for item in items:
        yield item


@pytest.fixture
def mock_sandbox():
    """Mock sandbox with required attributes."""
    sandbox = MagicMock()
    sandbox._provider = MagicMock()
    sandbox._skip_permissions = False
    sandbox._cwd = "/workspace"
    sandbox.event_buffer = MagicMock()
    sandbox.event_buffer.push = AsyncMock()
    return sandbox


class TestAgentManagerLazySpawn:
    """Test lazy agent spawning on first prompt."""

    @pytest.mark.asyncio
    async def test_spawns_agent_on_first_prompt(self, mock_sandbox):
        """Should spawn agent process when conversation_id is new."""
        mgr = AgentManager(mock_sandbox)

        with (
            patch("harnessbox.agent_manager.AgentProcess") as MockAgentProcess,
            patch("harnessbox.agent_manager.get_harness_type"),
        ):
            mock_process = MockAgentProcess.return_value
            mock_process.start = AsyncMock()
            mock_process.send_prompt = AsyncMock()
            mock_process.stream_turn = lambda: _async_gen_from(
                [MagicMock(session_id="conv-1", sequence=1)]
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
            patch("harnessbox.agent_manager.AgentProcess") as MockAgentProcess,
            patch("harnessbox.agent_manager.get_harness_type"),
        ):
            mock_process = MockAgentProcess.return_value
            mock_process.start = AsyncMock()
            mock_process.send_prompt = AsyncMock()
            mock_process.stream_turn = lambda: _async_gen_from(
                [MagicMock(session_id="conv-1", sequence=1)]
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
            patch("harnessbox.agent_manager.AgentProcess") as MockAgentProcess,
            patch("harnessbox.agent_manager.get_harness_type"),
        ):
            mock_process1 = MagicMock()
            mock_process1.start = AsyncMock()
            mock_process1.send_prompt = AsyncMock()
            mock_process1.stream_turn = lambda: _async_gen_from(
                [MagicMock(session_id="conv-1", sequence=1)]
            )

            mock_process2 = MagicMock()
            mock_process2.start = AsyncMock()
            mock_process2.send_prompt = AsyncMock()
            mock_process2.stream_turn = lambda: _async_gen_from(
                [MagicMock(session_id="conv-2", sequence=1)]
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
            patch("harnessbox.agent_manager.AgentProcess") as MockAgentProcess,
            patch("harnessbox.agent_manager.get_harness_type"),
        ):
            mock_process = MockAgentProcess.return_value
            mock_process.start = AsyncMock()
            mock_process.send_prompt = AsyncMock()
            mock_process.stop = AsyncMock()
            mock_process.stream_turn = lambda: _async_gen_from(
                [MagicMock(session_id="conv-1", sequence=1)]
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
            patch("harnessbox.agent_manager.AgentProcess") as MockAgentProcess,
            patch("harnessbox.agent_manager.get_harness_type"),
        ):
            mock_process1 = MagicMock()
            mock_process1.start = AsyncMock()
            mock_process1.send_prompt = AsyncMock()
            mock_process1.stop = AsyncMock()
            mock_process1.stream_turn = lambda: _async_gen_from(
                [MagicMock(session_id="conv-1", sequence=1)]
            )

            mock_process2 = MagicMock()
            mock_process2.start = AsyncMock()
            mock_process2.send_prompt = AsyncMock()
            mock_process2.stop = AsyncMock()
            mock_process2.stream_turn = lambda: _async_gen_from(
                [MagicMock(session_id="conv-2", sequence=1)]
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


class TestAgentManagerConversationList:
    """Test conversation listing."""

    def test_list_conversations(self, mock_sandbox):
        """Should return list of active conversation IDs."""
        mgr = AgentManager(mock_sandbox)
        mgr._agents = {"conv-1": MagicMock(), "conv-2": MagicMock()}

        result = mgr.list_conversations()

        assert set(result) == {"conv-1", "conv-2"}
