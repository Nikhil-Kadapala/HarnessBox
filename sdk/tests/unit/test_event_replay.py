"""Unit tests for EventReplay — SSE reconnection from stored events."""

from __future__ import annotations

import json

from harnessbox._server._storage.memory import MemoryBackend
from harnessbox._server.event_replay import EventReplay, _event_from_record
from harnessbox.events import EventBuffer
from harnessbox.streaming import UniversalEvent


def _make_event_record(seq: int, workspace_id: str = "ws-1", **overrides) -> dict[str, object]:
    """Build a storage record dict mimicking what MemoryBackend stores."""
    event_data = {
        "event_id": f"evt-{seq}",
        "sequence": seq,
        "timestamp": f"2026-05-27T10:00:{seq:02d}Z",
        "session_id": overrides.pop("session_id", "conv-1"),
        "event_type": overrides.pop("event_type", "message.delta"),
        "metadata": overrides.pop("metadata", {}),
        "delta": overrides.pop("delta", f"chunk-{seq}"),
        "cost_usd": overrides.pop("cost_usd", None),
    }
    return {
        "event_id": event_data["event_id"],
        "sequence": seq,
        "timestamp": event_data["timestamp"],
        "event_type": event_data["event_type"],
        "event_json": json.dumps(event_data),
        **overrides,
    }


class TestEventFromRecord:
    """Tests for the _event_from_record helper."""

    def test_reconstructs_valid_record(self) -> None:
        record = _make_event_record(5)
        event = _event_from_record(record)
        assert event is not None
        assert event.event_id == "evt-5"
        assert event.sequence == 5
        assert event.session_id == "conv-1"
        assert event.event_type == "message.delta"
        assert event.delta == "chunk-5"

    def test_returns_none_for_malformed_json(self) -> None:
        record = {"event_json": "not valid json {{{", "sequence": 1}
        event = _event_from_record(record)
        assert event is None

    def test_falls_back_to_record_fields_when_json_missing_keys(self) -> None:
        record = {
            "event_id": "fallback-id",
            "sequence": 7,
            "timestamp": "2026-01-01T00:00:00Z",
            "event_type": "turn.started",
            "event_json": json.dumps({"session_id": "s-1"}),
        }
        event = _event_from_record(record)
        assert event is not None
        assert event.event_id == "fallback-id"
        assert event.sequence == 7
        assert event.event_type == "turn.started"

    def test_handles_event_json_as_dict(self) -> None:
        data = {
            "event_id": "e-dict",
            "sequence": 3,
            "timestamp": "2026-01-01T00:00:00Z",
            "session_id": "s-2",
            "event_type": "message.delta",
            "metadata": {"key": "val"},
            "delta": "hello",
        }
        record = {"event_json": data, "sequence": 3}
        event = _event_from_record(record)
        assert event is not None
        assert event.event_id == "e-dict"
        assert event.metadata == {"key": "val"}

    def test_empty_record_returns_event_with_defaults(self) -> None:
        record = {"event_json": "{}"}
        event = _event_from_record(record)
        assert event is not None
        assert event.event_id == ""
        assert event.sequence == 0


class TestReplayFromSequence:
    """Tests for EventReplay.replay_from_sequence."""

    async def test_no_storage_yields_nothing(self) -> None:
        replay = EventReplay(storage=None)
        events = [e async for e in replay.replay_from_sequence("ws-1", 0)]
        assert events == []

    async def test_replays_events_after_sequence(self) -> None:
        storage = MemoryBackend()
        await storage.initialize()
        await storage.save_workspace(
            {
                "workspace_id": "ws-1",
                "remote": "r",
                "branch": "b",
                "provider": "e2b",
                "harness": "claude-code",
                "runtime_state": "active",
                "workflow_state": "ip",
                "created_at": "t",
                "last_active": "t",
                "config_json": "{}",
            }
        )
        records = [_make_event_record(i) for i in range(1, 6)]
        await storage.append_events("ws-1", records)

        replay = EventReplay(storage=storage)
        events = [e async for e in replay.replay_from_sequence("ws-1", 3)]
        assert len(events) == 2
        assert events[0].sequence == 4
        assert events[1].sequence == 5

    async def test_respects_limit(self) -> None:
        storage = MemoryBackend()
        await storage.initialize()
        await storage.save_workspace(
            {
                "workspace_id": "ws-1",
                "remote": "r",
                "branch": "b",
                "provider": "e2b",
                "harness": "claude-code",
                "runtime_state": "active",
                "workflow_state": "ip",
                "created_at": "t",
                "last_active": "t",
                "config_json": "{}",
            }
        )
        records = [_make_event_record(i) for i in range(1, 11)]
        await storage.append_events("ws-1", records)

        replay = EventReplay(storage=storage)
        events = [e async for e in replay.replay_from_sequence("ws-1", 0, limit=3)]
        assert len(events) == 3
        assert events[-1].sequence == 3

    async def test_skips_malformed_records(self) -> None:
        storage = MemoryBackend()
        await storage.initialize()
        await storage.save_workspace(
            {
                "workspace_id": "ws-1",
                "remote": "r",
                "branch": "b",
                "provider": "e2b",
                "harness": "claude-code",
                "runtime_state": "active",
                "workflow_state": "ip",
                "created_at": "t",
                "last_active": "t",
                "config_json": "{}",
            }
        )
        records = [
            _make_event_record(1),
            {
                "event_id": "bad",
                "sequence": 2,
                "timestamp": "t",
                "event_type": "x",
                "event_json": "{{{invalid",
            },
            _make_event_record(3),
        ]
        await storage.append_events("ws-1", records)

        replay = EventReplay(storage=storage)
        events = [e async for e in replay.replay_from_sequence("ws-1", 0)]
        assert len(events) == 2
        assert events[0].sequence == 1
        assert events[1].sequence == 3

    async def test_empty_workspace_yields_nothing(self) -> None:
        storage = MemoryBackend()
        await storage.initialize()
        await storage.save_workspace(
            {
                "workspace_id": "ws-1",
                "remote": "r",
                "branch": "b",
                "provider": "e2b",
                "harness": "claude-code",
                "runtime_state": "active",
                "workflow_state": "ip",
                "created_at": "t",
                "last_active": "t",
                "config_json": "{}",
            }
        )

        replay = EventReplay(storage=storage)
        events = [e async for e in replay.replay_from_sequence("ws-1", 0)]
        assert events == []

    async def test_nonexistent_workspace_yields_nothing(self) -> None:
        storage = MemoryBackend()
        await storage.initialize()

        replay = EventReplay(storage=storage)
        events = [e async for e in replay.replay_from_sequence("no-such-ws", 0)]
        assert events == []


class TestReplayThenLive:
    """Tests for EventReplay.replay_then_live — the SSE reconnection path."""

    async def test_replays_stored_then_streams_live(self) -> None:
        storage = MemoryBackend()
        await storage.initialize()
        await storage.save_workspace(
            {
                "workspace_id": "ws-1",
                "remote": "r",
                "branch": "b",
                "provider": "e2b",
                "harness": "claude-code",
                "runtime_state": "active",
                "workflow_state": "ip",
                "created_at": "t",
                "last_active": "t",
                "config_json": "{}",
            }
        )
        records = [_make_event_record(i) for i in range(1, 4)]
        await storage.append_events("ws-1", records)

        live_buffer = EventBuffer(initial_sequence=3)
        live_event = UniversalEvent(
            event_id="live-1",
            sequence=0,
            timestamp="t",
            session_id="conv-1",
            event_type="message.delta",
            delta="live-chunk",
        )
        await live_buffer.push(live_event)

        replay = EventReplay(storage=storage)
        collected: list[UniversalEvent] = []
        async for event in replay.replay_then_live("ws-1", 0, live_buffer, replay_limit=1000):
            collected.append(event)
            if event.sequence == 4:
                await live_buffer.close()

        assert len(collected) == 4
        assert collected[0].sequence == 1
        assert collected[1].sequence == 2
        assert collected[2].sequence == 3
        assert collected[3].sequence == 4
        assert collected[3].delta == "live-chunk"

    async def test_no_live_buffer_stops_after_replay(self) -> None:
        storage = MemoryBackend()
        await storage.initialize()
        await storage.save_workspace(
            {
                "workspace_id": "ws-1",
                "remote": "r",
                "branch": "b",
                "provider": "e2b",
                "harness": "claude-code",
                "runtime_state": "active",
                "workflow_state": "ip",
                "created_at": "t",
                "last_active": "t",
                "config_json": "{}",
            }
        )
        records = [_make_event_record(i) for i in range(1, 3)]
        await storage.append_events("ws-1", records)

        replay = EventReplay(storage=storage)
        events = [e async for e in replay.replay_then_live("ws-1", 0, None)]
        assert len(events) == 2

    async def test_live_buffer_continues_from_last_replayed_sequence(self) -> None:
        """Ensures no gap between replay and live stream."""
        storage = MemoryBackend()
        await storage.initialize()
        await storage.save_workspace(
            {
                "workspace_id": "ws-1",
                "remote": "r",
                "branch": "b",
                "provider": "e2b",
                "harness": "claude-code",
                "runtime_state": "active",
                "workflow_state": "ip",
                "created_at": "t",
                "last_active": "t",
                "config_json": "{}",
            }
        )
        records = [_make_event_record(i) for i in range(1, 6)]
        await storage.append_events("ws-1", records)

        live_buffer = EventBuffer(initial_sequence=5)
        live_evt = UniversalEvent(
            event_id="live-6",
            sequence=0,
            timestamp="t",
            session_id="conv-1",
            event_type="turn.ended",
        )
        await live_buffer.push(live_evt)

        replay = EventReplay(storage=storage)
        collected: list[UniversalEvent] = []
        async for event in replay.replay_then_live("ws-1", 3, live_buffer):
            collected.append(event)
            if event.event_type == "turn.ended":
                await live_buffer.close()

        # Should get seq 4, 5 from replay then seq 6 from live
        assert [e.sequence for e in collected] == [4, 5, 6]

    async def test_empty_replay_goes_straight_to_live(self) -> None:
        storage = MemoryBackend()
        await storage.initialize()
        await storage.save_workspace(
            {
                "workspace_id": "ws-1",
                "remote": "r",
                "branch": "b",
                "provider": "e2b",
                "harness": "claude-code",
                "runtime_state": "active",
                "workflow_state": "ip",
                "created_at": "t",
                "last_active": "t",
                "config_json": "{}",
            }
        )

        live_buffer = EventBuffer(initial_sequence=10)
        live_evt = UniversalEvent(
            event_id="live-11",
            sequence=0,
            timestamp="t",
            session_id="conv-1",
            event_type="message.delta",
            delta="direct",
        )
        await live_buffer.push(live_evt)

        replay = EventReplay(storage=storage)
        collected: list[UniversalEvent] = []
        async for event in replay.replay_then_live("ws-1", 10, live_buffer):
            collected.append(event)
            await live_buffer.close()

        assert len(collected) == 1
        assert collected[0].sequence == 11
        assert collected[0].delta == "direct"


class TestGetHistory:
    """Tests for EventReplay.get_history — the /history endpoint path."""

    async def test_returns_all_events_for_workspace(self) -> None:
        storage = MemoryBackend()
        await storage.initialize()
        await storage.save_workspace(
            {
                "workspace_id": "ws-1",
                "remote": "r",
                "branch": "b",
                "provider": "e2b",
                "harness": "claude-code",
                "runtime_state": "active",
                "workflow_state": "ip",
                "created_at": "t",
                "last_active": "t",
                "config_json": "{}",
            }
        )
        records = [_make_event_record(i) for i in range(1, 6)]
        await storage.append_events("ws-1", records)

        replay = EventReplay(storage=storage)
        events = [e async for e in replay.get_history("ws-1")]
        assert len(events) == 5

    async def test_filters_by_conversation_id(self) -> None:
        storage = MemoryBackend()
        await storage.initialize()
        await storage.save_workspace(
            {
                "workspace_id": "ws-1",
                "remote": "r",
                "branch": "b",
                "provider": "e2b",
                "harness": "claude-code",
                "runtime_state": "active",
                "workflow_state": "ip",
                "created_at": "t",
                "last_active": "t",
                "config_json": "{}",
            }
        )
        records = [
            _make_event_record(1, session_id="conv-A"),
            _make_event_record(2, session_id="conv-B"),
            _make_event_record(3, session_id="conv-A"),
            _make_event_record(4, session_id="conv-B"),
            _make_event_record(5, session_id="conv-A"),
        ]
        await storage.append_events("ws-1", records)

        replay = EventReplay(storage=storage)
        events = [e async for e in replay.get_history("ws-1", conversation_id="conv-A")]
        assert len(events) == 3
        assert all(e.session_id == "conv-A" for e in events)

    async def test_respects_after_sequence(self) -> None:
        storage = MemoryBackend()
        await storage.initialize()
        await storage.save_workspace(
            {
                "workspace_id": "ws-1",
                "remote": "r",
                "branch": "b",
                "provider": "e2b",
                "harness": "claude-code",
                "runtime_state": "active",
                "workflow_state": "ip",
                "created_at": "t",
                "last_active": "t",
                "config_json": "{}",
            }
        )
        records = [_make_event_record(i) for i in range(1, 6)]
        await storage.append_events("ws-1", records)

        replay = EventReplay(storage=storage)
        events = [e async for e in replay.get_history("ws-1", after_sequence=3)]
        assert len(events) == 2
        assert events[0].sequence == 4

    async def test_respects_limit(self) -> None:
        storage = MemoryBackend()
        await storage.initialize()
        await storage.save_workspace(
            {
                "workspace_id": "ws-1",
                "remote": "r",
                "branch": "b",
                "provider": "e2b",
                "harness": "claude-code",
                "runtime_state": "active",
                "workflow_state": "ip",
                "created_at": "t",
                "last_active": "t",
                "config_json": "{}",
            }
        )
        records = [_make_event_record(i) for i in range(1, 11)]
        await storage.append_events("ws-1", records)

        replay = EventReplay(storage=storage)
        events = [e async for e in replay.get_history("ws-1", limit=4)]
        assert len(events) == 4

    async def test_no_storage_yields_nothing(self) -> None:
        replay = EventReplay(storage=None)
        events = [e async for e in replay.get_history("ws-1")]
        assert events == []

    async def test_conversation_filter_with_event_json_as_string(self) -> None:
        """Verifies conversation filtering works when event_json is a JSON string."""
        storage = MemoryBackend()
        await storage.initialize()
        await storage.save_workspace(
            {
                "workspace_id": "ws-1",
                "remote": "r",
                "branch": "b",
                "provider": "e2b",
                "harness": "claude-code",
                "runtime_state": "active",
                "workflow_state": "ip",
                "created_at": "t",
                "last_active": "t",
                "config_json": "{}",
            }
        )
        records = [
            _make_event_record(1, session_id="target"),
            _make_event_record(2, session_id="other"),
        ]
        await storage.append_events("ws-1", records)

        replay = EventReplay(storage=storage)
        events = [e async for e in replay.get_history("ws-1", conversation_id="target")]
        assert len(events) == 1
        assert events[0].session_id == "target"

    async def test_storage_error_yields_nothing(self) -> None:
        """Verifies graceful handling when storage raises during get_events."""

        class BrokenStorage(MemoryBackend):
            async def get_events(self, workspace_id, **kwargs):
                raise RuntimeError("disk full")
                yield  # noqa: F841 - unreachable yield makes this an async generator

        storage = BrokenStorage()
        replay = EventReplay(storage=storage)
        events = [e async for e in replay.get_history("ws-1")]
        assert events == []
