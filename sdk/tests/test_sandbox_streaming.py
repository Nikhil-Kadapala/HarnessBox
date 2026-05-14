"""Tests for Sandbox.run_prompt_events() and session_id tracking."""

from __future__ import annotations

import json

import pytest

from harnessbox.sandbox import Sandbox
from harnessbox.streaming import EventType

from .conftest import MockProvider


@pytest.fixture
def provider() -> MockProvider:
    return MockProvider()


class TestRunPromptEvents:
    @pytest.mark.asyncio
    async def test_yields_typed_events(self, provider: MockProvider) -> None:
        provider._stream_lines = [
            json.dumps(
                {
                    "type": "stream_event",
                    "event": {
                        "type": "content_block_delta",
                        "delta": {"type": "text_delta", "text": "hello"},
                        "index": 0,
                    },
                }
            ),
            json.dumps({"type": "result", "session_id": "s-1", "duration_ms": 100}),
        ]
        sb = Sandbox(provider, skip_permissions=True, one_shot=True)
        await sb.setup()

        events = []
        async for e in sb.run_prompt_events("test"):
            events.append(e)

        assert len(events) == 2
        assert events[0].event_type == EventType.ITEM_DELTA
        assert events[0].delta == "hello"
        assert events[1].event_type == EventType.SESSION_ENDED

    @pytest.mark.asyncio
    async def test_filters_none_events(self, provider: MockProvider) -> None:
        provider._stream_lines = [
            json.dumps({"type": "init", "version": "1"}),
            json.dumps(
                {
                    "type": "stream_event",
                    "event": {
                        "type": "content_block_delta",
                        "delta": {"type": "text_delta", "text": "hi"},
                        "index": 0,
                    },
                }
            ),
            "not json at all",
        ]
        sb = Sandbox(provider, skip_permissions=True, one_shot=True)
        await sb.setup()

        events = []
        async for e in sb.run_prompt_events("test"):
            events.append(e)

        assert len(events) == 1
        assert events[0].delta == "hi"


class TestSessionIdTracking:
    @pytest.mark.asyncio
    async def test_extracts_session_id(self, provider: MockProvider) -> None:
        provider._stream_lines = [
            json.dumps({"type": "result", "session_id": "sess-abc", "duration_ms": 500}),
        ]
        sb = Sandbox(provider, skip_permissions=True, one_shot=True)
        await sb.setup()
        assert sb.agent_session_id is None

        async for _ in sb.run_prompt_events("first"):
            pass

        assert sb.agent_session_id == "sess-abc"

    @pytest.mark.asyncio
    async def test_resume_flag_in_second_call(self, provider: MockProvider) -> None:
        provider._stream_lines = [
            json.dumps({"type": "result", "session_id": "sess-123", "duration_ms": 100}),
        ]
        sb = Sandbox(provider, skip_permissions=True, one_shot=True)
        await sb.setup()

        async for _ in sb.run_prompt_events("first"):
            pass

        provider._stream_lines = [
            json.dumps({"type": "result", "session_id": "sess-123", "duration_ms": 200}),
        ]

        async for _ in sb.run_prompt_events("second"):
            pass

        stream_cmds = [c for c in provider._commands if "claude" in c]
        assert len(stream_cmds) >= 2
        assert "--resume" in stream_cmds[-1]
        assert "sess-123" in stream_cmds[-1]

    @pytest.mark.asyncio
    async def test_raw_run_prompt_also_tracks_session(self, provider: MockProvider) -> None:
        provider._stream_lines = [
            json.dumps({"type": "result", "session_id": "raw-sess"}),
        ]
        sb = Sandbox(provider, skip_permissions=True, one_shot=True)
        await sb.setup()

        async for _ in sb.run_prompt("test"):
            pass

        assert sb.agent_session_id == "raw-sess"
