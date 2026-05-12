"""Tests for Sandbox + EventHandler integration."""

from __future__ import annotations

import pytest

from harnessbox.sandbox import Sandbox
from harnessbox.security.events import CallbackHandler, EventType, SandboxEvent

from .conftest import MockProvider


class _EventCollector:
    """Collects events for test assertions."""

    def __init__(self) -> None:
        self.events: list[SandboxEvent] = []

    async def handle(self, event: SandboxEvent) -> None:
        self.events.append(event)


@pytest.fixture
def collector() -> _EventCollector:
    return _EventCollector()


@pytest.fixture
def event_provider() -> MockProvider:
    return MockProvider()


class TestSandboxWithEventHandler:
    @pytest.mark.asyncio
    async def test_setup_emits_event(
        self, event_provider: MockProvider, collector: _EventCollector
    ) -> None:
        sandbox = Sandbox(event_provider, event_handler=collector)
        await sandbox.setup()
        assert len(collector.events) == 1
        assert collector.events[0].event_type == EventType.SETUP_COMPLETE
        assert collector.events[0].action == "setup"
        assert collector.events[0].sandbox_id == "mock-sandbox-123"

    @pytest.mark.asyncio
    async def test_kill_emits_event(
        self, event_provider: MockProvider, collector: _EventCollector
    ) -> None:
        sandbox = Sandbox(event_provider, event_handler=collector)
        await sandbox.setup()
        collector.events.clear()
        await sandbox.kill()
        assert len(collector.events) == 1
        assert collector.events[0].event_type == EventType.SESSION_END
        assert collector.events[0].action == "kill"

    @pytest.mark.asyncio
    async def test_end_emits_event(
        self, event_provider: MockProvider, collector: _EventCollector
    ) -> None:
        sandbox = Sandbox(event_provider, event_handler=collector)
        await sandbox.setup()
        collector.events.clear()
        await sandbox.end()
        assert len(collector.events) == 1
        assert collector.events[0].event_type == EventType.SESSION_END
        assert collector.events[0].action == "end"

    @pytest.mark.asyncio
    async def test_run_command_emits_event(
        self, event_provider: MockProvider, collector: _EventCollector
    ) -> None:
        sandbox = Sandbox(event_provider, event_handler=collector)
        await sandbox.setup()
        collector.events.clear()
        await sandbox.run_command("echo hello")
        assert len(collector.events) == 1
        assert collector.events[0].event_type == EventType.COMMAND_RUN
        assert collector.events[0].action == "run_command"
        assert collector.events[0].resource == "echo hello"


class TestSandboxWithoutEventHandler:
    @pytest.mark.asyncio
    async def test_no_handler_works_normally(self, event_provider: MockProvider) -> None:
        sandbox = Sandbox(event_provider)
        await sandbox.setup()
        await sandbox.run_command("echo hello")
        await sandbox.kill()

    @pytest.mark.asyncio
    async def test_emit_event_skips_when_none(self, event_provider: MockProvider) -> None:
        sandbox = Sandbox(event_provider)
        await sandbox.setup()
        await sandbox._emit_event(EventType.COMMAND_RUN, action="test")


class TestEventHandlerErrorIsolation:
    @pytest.mark.asyncio
    async def test_handler_exception_does_not_break_sandbox(
        self, event_provider: MockProvider
    ) -> None:
        class BrokenHandler:
            async def handle(self, event: SandboxEvent) -> None:
                raise ValueError("handler crashed")

        sandbox = Sandbox(event_provider, event_handler=BrokenHandler())
        await sandbox.setup()
        await sandbox.run_command("echo hello")
        await sandbox.kill()


class TestCallbackHandlerIntegration:
    @pytest.mark.asyncio
    async def test_callback_receives_events(self, event_provider: MockProvider) -> None:
        received: list[SandboxEvent] = []
        handler = CallbackHandler(lambda e: received.append(e))
        sandbox = Sandbox(event_provider, event_handler=handler)
        await sandbox.setup()
        await sandbox.run_command("echo hello")
        assert len(received) == 2
        assert received[0].event_type == EventType.SETUP_COMPLETE
        assert received[1].event_type == EventType.COMMAND_RUN
