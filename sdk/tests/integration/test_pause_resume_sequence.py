"""Tests for event sequence continuity across workspace pause/resume cycles.

Verifies:
- Events are flushed to storage on pause
- EventBuffer hydrates from storage on reconnect
- Sequence numbers continue monotonically without gaps
- Replay from a given sequence returns correct events
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from harnessbox._storage.memory import MemoryBackend
from harnessbox.events import EventBuffer, deserialize_event
from harnessbox.streaming import EventType, ItemKind, UniversalEvent


@pytest.fixture
async def storage():
    """MemoryBackend initialized for tests."""
    backend = MemoryBackend()
    await backend.initialize()
    # Pre-create workspace so append_events works
    await backend.save_workspace(
        {
            "workspace_id": "ws-1",
            "remote": "https://github.com/test/repo.git",
            "branch": "main",
            "provider": "e2b",
            "provider_sandbox_id": None,
            "snapshot_id": None,
            "harness": "claude-code",
            "runtime_state": "active",
            "workflow_state": "in_progress",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_active": datetime.now(timezone.utc).isoformat(),
            "config_json": "{}",
        }
    )
    return backend


def _make_event(session_id: str, event_type: EventType = EventType.ITEM_DELTA) -> UniversalEvent:
    """Create a minimal UniversalEvent for testing."""
    return UniversalEvent(
        event_id="test-id",
        sequence=0,
        timestamp=datetime.now(timezone.utc).isoformat(),
        session_id=session_id,
        event_type=event_type,
        item_kind=ItemKind.MESSAGE,
        delta="hello",
    )


class TestPauseResumeSequence:
    """End-to-end sequence continuity across pause/resume cycles."""

    @pytest.mark.asyncio
    async def test_events_flushed_on_close(self, storage: MemoryBackend) -> None:
        """Events buffered in memory should be flushed to storage on close."""
        buf = EventBuffer(storage=storage, session_id="ws-1")

        await buf.push(_make_event("ws-1"))
        await buf.push(_make_event("ws-1"))
        await buf.push(_make_event("ws-1"))

        assert buf.latest_sequence == 3
        await buf.close()

        # Verify events are in storage
        stored = []
        async for record in storage.get_events("ws-1"):
            stored.append(record)
        assert len(stored) == 3
        assert stored[0]["sequence"] == 1
        assert stored[2]["sequence"] == 3

    @pytest.mark.asyncio
    async def test_hydrate_restores_ring_buffer(self, storage: MemoryBackend) -> None:
        """hydrate() should populate the ring buffer from storage."""
        # Phase 1: emit events and flush to storage
        buf1 = EventBuffer(storage=storage, session_id="ws-1")
        await buf1.push(_make_event("ws-1"))
        await buf1.push(_make_event("ws-1"))
        await buf1.push(_make_event("ws-1"))
        await buf1.close()

        # Phase 2: create new buffer (simulating reconnect) and hydrate
        buf2 = EventBuffer(storage=storage, session_id="ws-1", initial_sequence=0)
        assert buf2.size == 0

        await buf2.hydrate()

        assert buf2.size == 3
        assert buf2.latest_sequence == 3

    @pytest.mark.asyncio
    async def test_sequence_continues_after_hydration(self, storage: MemoryBackend) -> None:
        """New events after hydration should continue from the stored max sequence."""
        # Phase 1: emit 3 events and flush
        buf1 = EventBuffer(storage=storage, session_id="ws-1")
        await buf1.push(_make_event("ws-1"))
        await buf1.push(_make_event("ws-1"))
        await buf1.push(_make_event("ws-1"))
        await buf1.close()

        # Phase 2: hydrate and emit more events
        max_seq = await storage.get_max_sequence("ws-1")
        assert max_seq == 3

        buf2 = EventBuffer(storage=storage, session_id="ws-1", initial_sequence=max_seq)
        await buf2.hydrate()

        # Push new events — should start at 4
        e4 = await buf2.push(_make_event("ws-1"))
        e5 = await buf2.push(_make_event("ws-1"))

        assert e4.sequence == 4
        assert e5.sequence == 5
        assert buf2.latest_sequence == 5

        await buf2.close()

    @pytest.mark.asyncio
    async def test_replay_after_hydration(self, storage: MemoryBackend) -> None:
        """Replay from a given sequence should return correct events after hydration."""
        # Phase 1: emit 3 events
        buf1 = EventBuffer(storage=storage, session_id="ws-1")
        await buf1.push(_make_event("ws-1"))
        await buf1.push(_make_event("ws-1"))
        await buf1.push(_make_event("ws-1"))
        await buf1.close()

        # Phase 2: hydrate into new buffer
        max_seq = await storage.get_max_sequence("ws-1")
        buf2 = EventBuffer(storage=storage, session_id="ws-1", initial_sequence=max_seq)
        await buf2.hydrate()

        # Replay from sequence 1 → should get events 2 and 3
        replay = buf2.replay(after_sequence=1)
        assert len(replay) == 2
        assert replay[0].sequence == 2
        assert replay[1].sequence == 3

    @pytest.mark.asyncio
    async def test_no_duplicate_sequences_after_resume(self, storage: MemoryBackend) -> None:
        """Full pause/resume cycle should produce no duplicate sequences in storage."""
        # Phase 1: emit events and flush (simulating pause)
        buf1 = EventBuffer(storage=storage, session_id="ws-1")
        await buf1.push(_make_event("ws-1"))
        await buf1.push(_make_event("ws-1"))
        await buf1.push(_make_event("ws-1"))
        await buf1.close()

        # Phase 2: resume (hydrate + new events)
        max_seq = await storage.get_max_sequence("ws-1")
        buf2 = EventBuffer(storage=storage, session_id="ws-1", initial_sequence=max_seq)
        await buf2.hydrate()

        await buf2.push(_make_event("ws-1"))
        await buf2.push(_make_event("ws-1"))
        await buf2.close()

        # Verify all stored events have unique, monotonically increasing sequences
        all_events: list[dict[str, Any]] = []
        async for record in storage.get_events("ws-1"):
            all_events.append(record)

        sequences = [e["sequence"] for e in all_events]
        assert sequences == [1, 2, 3, 4, 5]


class TestDeserializeEvent:
    """Tests for the deserialize_event helper."""

    def test_roundtrip(self) -> None:
        """An event serialized then deserialized should preserve key fields."""
        original = UniversalEvent(
            event_id="e-1",
            sequence=42,
            timestamp="2026-01-01T00:00:00Z",
            session_id="s-1",
            event_type=EventType.ITEM_DELTA,
            item_kind=ItemKind.MESSAGE,
            delta="hello world",
        )
        serialized = original.to_dict()
        restored = deserialize_event(serialized)

        assert restored.event_id == "e-1"
        assert restored.sequence == 42
        assert restored.timestamp == "2026-01-01T00:00:00Z"
        assert restored.session_id == "s-1"
        assert restored.event_type == EventType.ITEM_DELTA
        assert restored.item_kind == ItemKind.MESSAGE
        assert restored.delta == "hello world"

    def test_handles_missing_optional_fields(self) -> None:
        """Events without optional fields should deserialize without error."""
        data = {
            "type": "session.started",
            "timestamp": "2026-01-01T00:00:00Z",
            "message": {
                "event_id": "e-2",
                "sequence": 1,
                "session_id": "s-1",
            },
        }
        event = deserialize_event(data)
        assert event.event_type == EventType.SESSION_STARTED
        assert event.item_kind is None
        assert event.delta is None
        assert event.cost_usd is None
