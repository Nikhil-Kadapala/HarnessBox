"""Tests for harnessbox.security.events — event system."""

from __future__ import annotations

import json

import pytest

from harnessbox.security.events import (
    CallbackHandler,
    EventHandler,
    EventType,
    JsonLogger,
    SandboxEvent,
)


class TestSandboxEvent:
    def test_construction(self) -> None:
        event = SandboxEvent(
            timestamp="2026-04-20T12:00:00Z",
            sandbox_id="sb-123",
            event_type=EventType.SETUP_COMPLETE,
            action="setup",
            resource="/workspace",
            reason="done",
            metadata={"key": "value"},
        )
        assert event.timestamp == "2026-04-20T12:00:00Z"
        assert event.sandbox_id == "sb-123"
        assert event.event_type == EventType.SETUP_COMPLETE
        assert event.action == "setup"
        assert event.resource == "/workspace"
        assert event.reason == "done"
        assert event.metadata == {"key": "value"}

    def test_defaults(self) -> None:
        event = SandboxEvent(
            timestamp="2026-04-20T12:00:00Z",
            sandbox_id=None,
            event_type=EventType.COMMAND_RUN,
            action="run_command",
        )
        assert event.sandbox_id is None
        assert event.resource is None
        assert event.reason == ""
        assert event.metadata == {}

    def test_frozen(self) -> None:
        event = SandboxEvent(
            timestamp="2026-04-20T12:00:00Z",
            sandbox_id="sb-123",
            event_type=EventType.SETUP_COMPLETE,
            action="setup",
        )
        with pytest.raises(AttributeError):
            event.action = "changed"  # type: ignore[misc]


class TestEventType:
    def test_values(self) -> None:
        assert EventType.SETUP_COMPLETE == "setup_complete"
        assert EventType.SESSION_END == "session_end"
        assert EventType.COMMAND_RUN == "command_run"
        assert EventType.STATE_CHANGED == "state_changed"

    def test_is_str(self) -> None:
        assert isinstance(EventType.SETUP_COMPLETE, str)


class TestEventHandlerProtocol:
    def test_protocol_compliance(self) -> None:
        assert isinstance(JsonLogger(), EventHandler)
        assert isinstance(CallbackHandler(lambda e: None), EventHandler)

    def test_custom_handler_satisfies_protocol(self) -> None:
        class MyHandler:
            async def handle(self, event: SandboxEvent) -> None:
                pass

        assert isinstance(MyHandler(), EventHandler)


class TestJsonLogger:
    @pytest.mark.asyncio
    async def test_outputs_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        logger = JsonLogger()
        event = SandboxEvent(
            timestamp="2026-04-20T12:00:00Z",
            sandbox_id="sb-123",
            event_type=EventType.SETUP_COMPLETE,
            action="setup",
        )
        await logger.handle(event)
        captured = capsys.readouterr()
        data = json.loads(captured.out.strip())
        assert data["event_type"] == "setup_complete"
        assert data["sandbox_id"] == "sb-123"
        assert data["action"] == "setup"

    @pytest.mark.asyncio
    async def test_handles_none_fields(self, capsys: pytest.CaptureFixture[str]) -> None:
        logger = JsonLogger()
        event = SandboxEvent(
            timestamp="2026-04-20T12:00:00Z",
            sandbox_id=None,
            event_type=EventType.SESSION_END,
            action="kill",
        )
        await logger.handle(event)
        captured = capsys.readouterr()
        data = json.loads(captured.out.strip())
        assert data["sandbox_id"] is None


class TestCallbackHandler:
    @pytest.mark.asyncio
    async def test_invokes_callback(self) -> None:
        received: list[SandboxEvent] = []
        handler = CallbackHandler(lambda e: received.append(e))
        event = SandboxEvent(
            timestamp="2026-04-20T12:00:00Z",
            sandbox_id="sb-123",
            event_type=EventType.COMMAND_RUN,
            action="run_command",
            resource="echo hello",
        )
        await handler.handle(event)
        assert len(received) == 1
        assert received[0].resource == "echo hello"

    @pytest.mark.asyncio
    async def test_invokes_async_callback(self) -> None:
        received: list[SandboxEvent] = []

        async def async_cb(event: SandboxEvent) -> None:
            received.append(event)

        handler = CallbackHandler(async_cb)
        event = SandboxEvent(
            timestamp="2026-04-20T12:00:00Z",
            sandbox_id="sb-123",
            event_type=EventType.SETUP_COMPLETE,
            action="setup",
        )
        await handler.handle(event)
        assert len(received) == 1
