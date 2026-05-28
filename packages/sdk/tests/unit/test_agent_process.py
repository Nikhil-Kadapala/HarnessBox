"""Unit tests for AgentProcess — command sending, polling, and cost tracking.

Tests use a FakeProvider that wires stdout injection through process.start(),
avoiding direct access to _running, _pid, or _stdout_queue.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from harnessbox.process import AgentProcess
from harnessbox.streaming import EventType, StreamParser, UniversalEvent


class FakeProvider:
    """Minimal provider for AgentProcess unit tests.

    Captures stdin writes and exposes inject_stdout() to simulate agent output.
    """

    def __init__(self) -> None:
        self._on_stdout: Any = None
        self.stdin_writes: list[str] = []

    async def start_session(self, command: str, cwd: str, on_stdout: Any) -> int:
        self._on_stdout = on_stdout
        return 42

    async def send_stdin(self, pid: int, data: str) -> None:
        self.stdin_writes.append(data)

    def inject_stdout(self, line: str) -> None:
        """Simulate a line of NDJSON output from the agent process."""
        self._on_stdout(type("Data", (), {"line": line})())


def _started_process(
    provider: FakeProvider | None = None, turn_timeout: float | None = None
) -> tuple[FakeProvider, AgentProcess]:
    """Create and start an AgentProcess, returning (provider, process)."""
    prov = provider or FakeProvider()
    kwargs: dict[str, Any] = {}
    if turn_timeout is not None:
        kwargs["turn_timeout"] = turn_timeout
    process = AgentProcess(prov, StreamParser(persistent=True), **kwargs)
    return prov, process


async def _start(process: AgentProcess, provider: FakeProvider) -> None:
    await process.start("claude --output-format stream-json", "/workspace")


# --- send_command tests ---


class TestSendCommand:
    @pytest.mark.asyncio
    async def test_captures_structured_stdout_content(self) -> None:
        provider, process = _started_process()
        await _start(process, provider)

        await process._stdout_queue.put(
            json.dumps(
                {
                    "type": "user",
                    "message": {
                        "content": [
                            {
                                "type": "local-command-stdout",
                                "text": "**Tokens:** 153.7k / 200k (77%)",
                            }
                        ]
                    },
                }
            )
        )
        await process._stdout_queue.put(
            json.dumps({"type": "result", "subtype": "success", "total_cost_usd": 0.12})
        )

        result = await process.send_command("/context")

        assert json.loads(provider.stdin_writes[0])["message"]["content"] == "/context"
        assert result["output"] == "**Tokens:** 153.7k / 200k (77%)"
        assert result["total_cost_usd"] == 0.12

    @pytest.mark.asyncio
    async def test_captures_nested_tool_result_content(self) -> None:
        provider, process = _started_process()
        await _start(process, provider)

        await process._stdout_queue.put(
            json.dumps(
                {
                    "type": "user",
                    "message": {
                        "content": [
                            {
                                "type": "tool_result",
                                "content": [{"type": "text", "text": "Tokens: 1.2k / 10k (12%)"}],
                            }
                        ]
                    },
                }
            )
        )
        await process._stdout_queue.put(json.dumps({"type": "result", "subtype": "success"}))

        result = await process.send_command("/context")
        assert result["output"] == "Tokens: 1.2k / 10k (12%)"


# --- poll_status tests ---


class TestPollStatus:
    @pytest.mark.asyncio
    async def test_returns_context_and_cost_events(self) -> None:
        provider, process = _started_process()
        await _start(process, provider)

        async def mock_send_command(cmd: str, timeout: float = 10) -> dict[str, Any]:
            if cmd == "/context":
                return {"output": "**Tokens:** 50k / 200k (25%)"}
            if cmd == "/cost":
                return {
                    "total_cost_usd": 0.05,
                    "modelUsage": {
                        "claude-sonnet-4.5": {
                            "inputTokens": 1000,
                            "outputTokens": 500,
                            "costUSD": 0.05,
                        }
                    },
                }
            return {}

        process.send_command = mock_send_command  # type: ignore[assignment]

        events = await process.poll_status(session_id="sess-1")

        assert len(events) == 2
        assert events[0].event_type == EventType.CONTEXT_UPDATE
        assert events[0].metadata["tokens_used"] == 50_000
        assert events[0].session_id == "sess-1"
        assert events[1].event_type == EventType.COST_UPDATE
        assert events[1].metadata["total_cost_usd"] == 0.05

    @pytest.mark.asyncio
    async def test_skip_cost_omits_cost_event(self) -> None:
        provider, process = _started_process()
        await _start(process, provider)

        async def mock_send_command(cmd: str, timeout: float = 10) -> dict[str, Any]:
            if cmd == "/context":
                return {"output": "**Tokens:** 50k / 200k (25%)"}
            raise AssertionError("/cost should not be called")

        process.send_command = mock_send_command  # type: ignore[assignment]

        events = await process.poll_status(skip_cost=True)
        assert len(events) == 1
        assert events[0].event_type == EventType.CONTEXT_UPDATE

    @pytest.mark.asyncio
    async def test_timeout_returns_empty(self) -> None:
        provider, process = _started_process()
        await _start(process, provider)

        async def mock_send_command(cmd: str, timeout: float = 10) -> dict[str, Any]:
            raise asyncio.TimeoutError()

        process.send_command = mock_send_command  # type: ignore[assignment]

        events = await process.poll_status()
        assert events == []

    @pytest.mark.asyncio
    async def test_dead_process_returns_empty(self) -> None:
        _, process = _started_process()
        # Process never started, so is_running is False
        events = await process.poll_status()
        assert events == []

    @pytest.mark.asyncio
    async def test_raises_during_active_turn(self) -> None:
        provider, process = _started_process()
        await _start(process, provider)
        process._turn_active = True

        with pytest.raises(RuntimeError, match="Cannot poll status during an active turn"):
            await process.poll_status()


# --- cost_update_from_result tests ---


class TestCostUpdate:
    def test_with_model_usage_returns_cost_event(self) -> None:
        _, process = _started_process()

        turn_end = UniversalEvent(
            event_id="e1",
            sequence=1,
            timestamp="2026-01-01T00:00:00Z",
            session_id="sess-1",
            event_type=EventType.TURN_ENDED,
            cost_usd=0.08,
            metadata={
                "model_usage": {"claude-sonnet-4.5": {"inputTokens": 2000, "outputTokens": 800}}
            },
        )

        event = process.cost_update_from_result(turn_end, session_id="sess-1")

        assert event is not None
        assert event.event_type == EventType.COST_UPDATE
        assert event.metadata["total_cost_usd"] == 0.08
        assert event.metadata["turn_count"] == 1
        assert "claude-sonnet-4.5" in event.metadata["per_model"]

    def test_updates_cost_metrics_cumulatively(self) -> None:
        _, process = _started_process()

        for i in range(3):
            turn_end = UniversalEvent(
                event_id=f"e{i}",
                sequence=i,
                timestamp="2026-01-01T00:00:00Z",
                session_id="sess-1",
                event_type=EventType.TURN_ENDED,
                cost_usd=0.01 * (i + 1),
                metadata={
                    "model_usage": {"claude-haiku-4.5": {"inputTokens": 100, "outputTokens": 50}}
                },
            )
            process.cost_update_from_result(turn_end)

        assert process.cost_metrics.turn_count == 3
        assert process.cost_metrics.total_cost_usd == 0.03

    def test_no_model_usage_returns_none(self) -> None:
        _, process = _started_process()

        turn_end = UniversalEvent(
            event_id="e1",
            sequence=1,
            timestamp="2026-01-01T00:00:00Z",
            session_id="sess-1",
            event_type=EventType.TURN_ENDED,
            cost_usd=0.05,
            metadata={},
        )

        assert process.cost_update_from_result(turn_end) is None


# --- turn_timeout test ---


class TestTurnTimeout:
    @pytest.mark.asyncio
    async def test_configurable_timeout_emits_error_event(self) -> None:
        provider, process = _started_process(turn_timeout=0.01)
        await _start(process, provider)

        events: list[UniversalEvent] = []
        async for event in process.stream_turn():
            events.append(event)

        assert len(events) == 1
        assert events[0].event_type == EventType.ERROR
        assert "0.01s" in (events[0].error_message or "")
