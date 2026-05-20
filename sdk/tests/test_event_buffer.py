"""Tests for harnessbox.events — EventBuffer ring buffer + broadcast."""

from __future__ import annotations

import asyncio

import pytest

from harnessbox.events import EventBuffer
from harnessbox.streaming import EventType, UniversalEvent


def _make_event(seq: int, session_id: str = "s-1") -> UniversalEvent:
    return UniversalEvent(
        event_id=f"e-{seq}",
        sequence=seq,
        timestamp="2026-01-01T00:00:00Z",
        session_id=session_id,
        event_type=EventType.ITEM_DELTA,
        delta=f"chunk-{seq}",
    )


class TestEventBufferPush:
    @pytest.mark.asyncio
    async def test_push_adds_to_ring(self) -> None:
        buf = EventBuffer()
        await buf.push(_make_event(1))
        assert buf.size == 1
        assert buf.latest_sequence == 1

    @pytest.mark.asyncio
    async def test_ring_bounded(self) -> None:
        buf = EventBuffer()
        buf._ring = __import__("collections").deque(maxlen=3)
        for i in range(5):
            await buf.push(_make_event(i + 1))
        assert buf.size == 3
        assert buf.latest_sequence == 5

    @pytest.mark.asyncio
    async def test_latest_sequence_empty(self) -> None:
        buf = EventBuffer()
        assert buf.latest_sequence == 0

    @pytest.mark.asyncio
    async def test_push_returns_sequenced_event(self) -> None:
        buf = EventBuffer()
        original = _make_event(0)
        returned = await buf.push(original)
        assert returned.sequence == 1
        assert returned.event_id == original.event_id
        assert returned.delta == original.delta

    @pytest.mark.asyncio
    async def test_push_return_matches_ring(self) -> None:
        buf = EventBuffer()
        returned = await buf.push(_make_event(0))
        ring_events = buf.replay()
        assert ring_events[0].sequence == returned.sequence
        assert ring_events[0] is returned


class TestEventBufferReplay:
    @pytest.mark.asyncio
    async def test_replay_all(self) -> None:
        buf = EventBuffer()
        for i in range(3):
            await buf.push(_make_event(i + 1))
        events = buf.replay()
        assert len(events) == 3

    @pytest.mark.asyncio
    async def test_replay_after_sequence(self) -> None:
        buf = EventBuffer()
        for i in range(5):
            await buf.push(_make_event(i + 1))
        events = buf.replay(after_sequence=3)
        assert len(events) == 2
        assert events[0].sequence == 4
        assert events[1].sequence == 5

    @pytest.mark.asyncio
    async def test_replay_after_latest_returns_empty(self) -> None:
        buf = EventBuffer()
        for i in range(3):
            await buf.push(_make_event(i + 1))
        events = buf.replay(after_sequence=3)
        assert len(events) == 0


class TestEventBufferSubscription:
    @pytest.mark.asyncio
    async def test_subscribe_and_receive(self) -> None:
        buf = EventBuffer()
        replay, sub_id = buf.subscribe()
        queue = buf.get_queue(sub_id)
        assert len(replay) == 0

        await buf.push(_make_event(1))
        event = queue.get_nowait()
        assert event is not None
        assert event.sequence == 1

        buf.unsubscribe(sub_id)

    @pytest.mark.asyncio
    async def test_subscribe_with_replay(self) -> None:
        buf = EventBuffer()
        await buf.push(_make_event(1))
        await buf.push(_make_event(2))
        await buf.push(_make_event(3))

        replay, sub_id = buf.subscribe(last_event_id=1)
        assert len(replay) == 2
        assert replay[0].sequence == 2
        assert replay[1].sequence == 3
        buf.unsubscribe(sub_id)

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self) -> None:
        buf = EventBuffer()
        _, sub1 = buf.subscribe()
        _, sub2 = buf.subscribe()
        q1 = buf.get_queue(sub1)
        q2 = buf.get_queue(sub2)

        await buf.push(_make_event(1))

        assert q1.get_nowait().sequence == 1
        assert q2.get_nowait().sequence == 1

        buf.unsubscribe(sub1)
        buf.unsubscribe(sub2)


class TestEventBufferStream:
    @pytest.mark.asyncio
    async def test_stream_replays_then_live(self) -> None:
        buf = EventBuffer()
        await buf.push(_make_event(1))
        await buf.push(_make_event(2))

        collected: list[UniversalEvent] = []

        async def collect() -> None:
            async for event in buf.stream(last_event_id=0):
                collected.append(event)
                if len(collected) == 3:
                    break

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.01)
        await buf.push(_make_event(3))
        await asyncio.wait_for(task, timeout=1.0)

        assert len(collected) == 3
        assert collected[0].sequence == 1
        assert collected[2].sequence == 3

    @pytest.mark.asyncio
    async def test_stream_close_terminates(self) -> None:
        buf = EventBuffer()
        await buf.push(_make_event(1))

        collected: list[UniversalEvent] = []

        async def collect() -> None:
            async for event in buf.stream():
                collected.append(event)

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.01)
        await buf.close()
        await asyncio.wait_for(task, timeout=1.0)

        assert len(collected) == 1


class TestEventBufferFlush:
    @pytest.mark.asyncio
    async def test_flush_with_content_parts(self) -> None:
        """Flush should serialize events with ContentPart tuples without error."""
        from harnessbox._storage.memory import MemoryBackend
        from harnessbox.streaming import ContentPart

        storage = MemoryBackend()
        await storage.initialize()
        # Save a dummy workspace so append_events has a target
        await storage.save_workspace(
            {
                "workspace_id": "w-flush",
                "remote": "",
                "branch": "",
                "provider": "e2b",
                "provider_sandbox_id": None,
                "snapshot_id": None,
                "harness": "claude-code",
                "status": "active",
                "created_at": "2026-01-01T00:00:00Z",
                "last_active": "2026-01-01T00:00:00Z",
                "config_json": "{}",
            }
        )

        buf = EventBuffer(storage=storage, session_id="w-flush")

        event = UniversalEvent(
            event_id="ev-1",
            sequence=0,
            timestamp="2026-01-01T00:00:00Z",
            session_id="w-flush",
            event_type=EventType.ITEM_DELTA,
            content=(ContentPart(type="text", text="hello world"),),
            delta="hello world",
        )
        await buf.push(event)

        # Force flush — should not raise "asdict() should be called on dataclass instances"
        await buf._flush_events()

        # Verify event was persisted
        persisted = []
        async for e in storage.get_events("w-flush"):
            persisted.append(e)
        assert len(persisted) == 1

        # Cleanup
        if buf._flush_task:
            buf._flush_task.cancel()
            try:
                await buf._flush_task
            except asyncio.CancelledError:
                pass


class TestEventBufferInSandbox:
    @pytest.mark.asyncio
    async def test_sandbox_pushes_to_buffer(self) -> None:
        import json

        from harnessbox.sandbox import Sandbox

        from .conftest import MockProvider

        provider = MockProvider()
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
        sb = Sandbox(provider, skip_permissions=True)
        await sb.setup()

        async for _ in sb.send_message("test"):
            pass

        assert sb.event_buffer.size >= 2
