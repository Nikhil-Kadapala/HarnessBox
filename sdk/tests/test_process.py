import asyncio
import json

import pytest

from harnessbox.process import AgentProcess
from harnessbox.streaming import EventType, StreamParser, UniversalEvent


class StdinProvider:
    def __init__(self) -> None:
        self.stdin: list[str] = []

    async def send_stdin(self, pid: int, data: str) -> None:
        self.stdin.append(data)


@pytest.mark.asyncio
async def test_send_command_captures_structured_stdout_content() -> None:
    provider = StdinProvider()
    process = AgentProcess(provider, StreamParser(persistent=True))
    process._running = True
    process._pid = 42

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
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "total_cost_usd": 0.12,
            }
        )
    )

    result = await process.send_command("/context")

    assert json.loads(provider.stdin[0])["message"]["content"] == "/context"
    assert result["output"] == "**Tokens:** 153.7k / 200k (77%)"
    assert result["total_cost_usd"] == 0.12


@pytest.mark.asyncio
async def test_send_command_captures_nested_content() -> None:
    provider = StdinProvider()
    process = AgentProcess(provider, StreamParser(persistent=True))
    process._running = True
    process._pid = 42

    await process._stdout_queue.put(
        json.dumps(
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Tokens: 1.2k / 10k (12%)",
                                }
                            ],
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


@pytest.mark.asyncio
async def test_poll_status_returns_context_and_cost_events() -> None:
    provider = StdinProvider()
    process = AgentProcess(provider, StreamParser(persistent=True))
    process._running = True
    process._pid = 42

    async def mock_send_command(cmd: str, timeout: float = 10) -> dict:  # type: ignore[type-arg]
        if cmd == "/context":
            return {"output": "**Tokens:** 50k / 200k (25%)"}
        if cmd == "/cost":
            return {
                "total_cost_usd": 0.05,
                "modelUsage": {
                    "claude-sonnet-4.5": {"inputTokens": 1000, "outputTokens": 500, "costUSD": 0.05}
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
async def test_poll_status_skip_cost_omits_cost_event() -> None:
    provider = StdinProvider()
    process = AgentProcess(provider, StreamParser(persistent=True))
    process._running = True
    process._pid = 42

    async def mock_send_command(cmd: str, timeout: float = 10) -> dict:  # type: ignore[type-arg]
        if cmd == "/context":
            return {"output": "**Tokens:** 50k / 200k (25%)"}
        raise AssertionError("/cost should not be called")

    process.send_command = mock_send_command  # type: ignore[assignment]

    events = await process.poll_status(skip_cost=True)

    assert len(events) == 1
    assert events[0].event_type == EventType.CONTEXT_UPDATE


@pytest.mark.asyncio
async def test_poll_status_timeout_returns_empty() -> None:
    provider = StdinProvider()
    process = AgentProcess(provider, StreamParser(persistent=True))
    process._running = True
    process._pid = 42

    async def mock_send_command(cmd: str, timeout: float = 10) -> dict:  # type: ignore[type-arg]
        raise asyncio.TimeoutError()

    process.send_command = mock_send_command  # type: ignore[assignment]

    events = await process.poll_status()
    assert events == []


@pytest.mark.asyncio
async def test_poll_status_dead_process_returns_empty() -> None:
    provider = StdinProvider()
    process = AgentProcess(provider, StreamParser(persistent=True))
    process._running = False
    process._pid = None

    events = await process.poll_status()
    assert events == []


@pytest.mark.asyncio
async def test_poll_status_raises_during_active_turn() -> None:
    provider = StdinProvider()
    process = AgentProcess(provider, StreamParser(persistent=True))
    process._running = True
    process._pid = 42
    process._turn_active = True

    with pytest.raises(RuntimeError, match="Cannot poll status during an active turn"):
        await process.poll_status()


# --- cost_update_from_result tests ---


def test_cost_update_from_result_with_model_usage() -> None:
    provider = StdinProvider()
    process = AgentProcess(provider, StreamParser(persistent=True))

    turn_end = UniversalEvent(
        event_id="e1",
        sequence=1,
        timestamp="2026-01-01T00:00:00Z",
        session_id="sess-1",
        event_type=EventType.TURN_ENDED,
        cost_usd=0.08,
        metadata={"model_usage": {"claude-sonnet-4.5": {"inputTokens": 2000, "outputTokens": 800}}},
    )

    event = process.cost_update_from_result(turn_end, session_id="sess-1")

    assert event is not None
    assert event.event_type == EventType.COST_UPDATE
    assert event.metadata["total_cost_usd"] == 0.08
    assert event.metadata["turn_count"] == 1
    assert "claude-sonnet-4.5" in event.metadata["per_model"]


def test_cost_update_from_result_updates_cost_metrics() -> None:
    provider = StdinProvider()
    process = AgentProcess(provider, StreamParser(persistent=True))

    turn_end = UniversalEvent(
        event_id="e1",
        sequence=1,
        timestamp="2026-01-01T00:00:00Z",
        session_id="sess-1",
        event_type=EventType.TURN_ENDED,
        cost_usd=0.10,
        metadata={"model_usage": {"claude-opus-4": {"inputTokens": 5000, "outputTokens": 2000}}},
    )

    process.cost_update_from_result(turn_end)

    assert process.cost_metrics.total_cost_usd == 0.10
    assert process.cost_metrics.turn_count == 1
    assert "claude-opus-4" in process.cost_metrics.per_model


def test_cost_update_from_result_no_model_usage_returns_none() -> None:
    provider = StdinProvider()
    process = AgentProcess(provider, StreamParser(persistent=True))

    turn_end = UniversalEvent(
        event_id="e1",
        sequence=1,
        timestamp="2026-01-01T00:00:00Z",
        session_id="sess-1",
        event_type=EventType.TURN_ENDED,
        cost_usd=0.05,
        metadata={},
    )

    event = process.cost_update_from_result(turn_end)
    assert event is None


def test_cost_metrics_accumulates_across_turns() -> None:
    provider = StdinProvider()
    process = AgentProcess(provider, StreamParser(persistent=True))

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


# --- turn_timeout tests ---


@pytest.mark.asyncio
async def test_turn_timeout_configurable() -> None:
    provider = StdinProvider()
    process = AgentProcess(provider, StreamParser(persistent=True), turn_timeout=0.01)
    process._running = True
    process._pid = 42

    events: list[UniversalEvent] = []
    async for event in process.stream_turn():
        events.append(event)

    assert len(events) == 1
    assert events[0].event_type == EventType.ERROR
    assert "0s" in (events[0].error_message or "")
