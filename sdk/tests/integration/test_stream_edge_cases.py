"""Tests for harnessbox.streaming — universal event schema + stream parser."""

from __future__ import annotations

from harnessbox.streaming import (
    EventType,
    StreamParser,
    ToolKind,
    UniversalEvent,
    classify_tool,
    parse_stream_line,
)

from ._streaming_helpers import _line, _stream_event

# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_string(self) -> None:
        assert StreamParser().parse("") is None

    def test_whitespace_only(self) -> None:
        assert StreamParser().parse("   ") is None

    def test_malformed_json(self) -> None:
        assert StreamParser().parse("not json {") is None

    def test_unknown_type(self) -> None:
        assert StreamParser().parse(_line(type="init")) is None

    def test_unknown_stream_event(self) -> None:
        assert StreamParser().parse(_stream_event("ping")) is None

    def test_parse_line_returns_list(self) -> None:
        p = StreamParser()
        events = p.parse_line(
            _stream_event(
                "content_block_delta",
                delta={"type": "text_delta", "text": "hi"},
                index=0,
            )
        )
        assert isinstance(events, list)

    def test_parse_line_empty_for_unknown(self) -> None:
        p = StreamParser()
        assert p.parse_line(_line(type="unknown")) == []


# Replay suppression (multi-turn)
# ---------------------------------------------------------------------------


class TestReplaySuppression:
    """Verify that replayed slash-command outputs don't emit spurious TURN_ENDED."""

    def _init_line(self, session_id: str = "sess-1") -> str:
        return _line(
            type="system",
            subtype="init",
            session_id=session_id,
            tools=["Bash", "Read"],
            cwd="/workspace",
        )

    def _replay_user(self) -> str:
        return _line(
            type="user",
            message={
                "role": "user",
                "content": "<local-command-stdout>cost info</local-command-stdout>",
            },
            session_id="sess-1",
            parent_tool_use_id=None,
            isReplay=True,
        )

    def _replay_result(self) -> str:
        return _line(
            type="result",
            subtype="success",
            is_error=False,
            duration_ms=5,
            duration_api_ms=100,
            num_turns=10,
            result="",
            session_id="sess-1",
            total_cost_usd=0.05,
            usage={},
        )

    def _real_result(self) -> str:
        return _line(
            type="result",
            subtype="success",
            is_error=False,
            duration_ms=2000,
            duration_api_ms=5000,
            num_turns=1,
            result="Hello!",
            session_id="sess-1",
            total_cost_usd=0.10,
            usage={"input_tokens": 100, "output_tokens": 50},
        )

    def test_replay_result_suppressed(self) -> None:
        """Replay user+result pair should not emit TURN_ENDED."""
        p = StreamParser(persistent=True)
        all_events: list[UniversalEvent] = []

        # Simulate turn 1 completing (so turn 2 emits TURN_STARTED)
        all_events.extend(p.parse_line(self._init_line()))  # SESSION_STARTED (turn 1)
        all_events.extend(p.parse_line(self._real_result()))  # TURN_ENDED (turn 1)

        # Turn 2: init with replay
        all_events_t2: list[UniversalEvent] = []
        all_events_t2.extend(p.parse_line(self._init_line()))  # TURN_STARTED (turn 2)
        # Replay cycle
        all_events_t2.extend(p.parse_line(self._replay_user()))
        all_events_t2.extend(p.parse_line(self._replay_result()))
        # Post-replay init — suppressed
        all_events_t2.extend(p.parse_line(self._init_line()))
        # Real result
        all_events_t2.extend(p.parse_line(self._real_result()))

        turn_started = [e for e in all_events_t2 if e.event_type == EventType.TURN_STARTED]
        turn_ended = [e for e in all_events_t2 if e.event_type == EventType.TURN_ENDED]
        assert len(turn_started) == 1, f"Expected 1 TURN_STARTED, got {len(turn_started)}"
        assert len(turn_ended) == 1, f"Expected 1 TURN_ENDED, got {len(turn_ended)}"
        assert turn_ended[0].cost_usd == 0.10
        assert turn_ended[0].metadata["result"] == "Hello!"

    def test_multiple_replay_cycles(self) -> None:
        """Multiple replay pairs (e.g. /context + /cost) all get suppressed."""
        p = StreamParser(persistent=True)

        # Complete turn 1 so subsequent inits emit TURN_STARTED
        p.parse_line(self._init_line())
        p.parse_line(self._real_result())

        # Turn 2 with multiple replay cycles
        all_events: list[UniversalEvent] = []
        all_events.extend(p.parse_line(self._init_line()))
        # First replay cycle
        all_events.extend(p.parse_line(self._replay_user()))
        all_events.extend(p.parse_line(self._replay_result()))
        all_events.extend(p.parse_line(self._init_line()))
        # Second replay cycle
        all_events.extend(p.parse_line(self._replay_user()))
        all_events.extend(p.parse_line(self._replay_result()))
        all_events.extend(p.parse_line(self._init_line()))
        # Real result
        all_events.extend(p.parse_line(self._real_result()))

        turn_ended = [e for e in all_events if e.event_type == EventType.TURN_ENDED]
        assert len(turn_ended) == 1
        assert turn_ended[0].metadata["result"] == "Hello!"

    def test_no_replay_on_first_turn(self) -> None:
        """First turn has no replays — passes through normally."""
        p = StreamParser(persistent=True)
        all_events: list[UniversalEvent] = []

        all_events.extend(p.parse_line(self._init_line()))
        all_events.extend(p.parse_line(self._real_result()))

        session_started = [e for e in all_events if e.event_type == EventType.SESSION_STARTED]
        turn_ended = [e for e in all_events if e.event_type == EventType.TURN_ENDED]
        assert len(session_started) == 1
        assert len(turn_ended) == 1


# Tool classification
# ---------------------------------------------------------------------------


class TestToolClassification:
    def test_bash(self) -> None:
        assert classify_tool("Bash") == ToolKind.BASH

    def test_file_write(self) -> None:
        assert classify_tool("Write") == ToolKind.FILE_CHANGE

    def test_file_read(self) -> None:
        assert classify_tool("Read") == ToolKind.FILE_READ

    def test_web(self) -> None:
        assert classify_tool("WebFetch") == ToolKind.WEB

    def test_unknown(self) -> None:
        assert classify_tool("CustomTool") == ToolKind.OTHER


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


class TestParseStreamLine:
    def test_convenience_function(self) -> None:
        e = parse_stream_line(
            _stream_event(
                "content_block_delta",
                delta={"type": "text_delta", "text": "hi"},
                index=0,
            )
        )
        assert e is not None
        assert e.event_type == EventType.ITEM_DELTA
        assert e.delta == "hi"

    def test_returns_none_for_unknown(self) -> None:
        assert parse_stream_line(_line(type="unknown_thing")) is None


# NDJSON regression fixture — recorded from a real Claude Code session
# ---------------------------------------------------------------------------


class TestNDJSONFixture:
    def test_recorded_turn_single_turn_ended(self) -> None:
        """Replay a real recorded NDJSON session and verify event invariants."""
        from pathlib import Path

        fixture_path = Path(__file__).parent.parent / "fixtures" / "recorded_turn.ndjson"
        lines = fixture_path.read_text().strip().splitlines()

        p = StreamParser(persistent=True)
        all_events: list[UniversalEvent] = []
        for line in lines:
            all_events.extend(p.parse_line(line))

        turn_ended = [e for e in all_events if e.event_type == EventType.TURN_ENDED]
        assert len(turn_ended) == 1, f"Expected 1 TURN_ENDED, got {len(turn_ended)}"
        assert turn_ended[0].cost_usd is not None
        assert turn_ended[0].duration_ms is not None

        session_ids = {e.session_id for e in all_events if e.session_id}
        assert len(session_ids) == 1, f"Expected 1 session_id, got {session_ids}"

        event_types = [e.event_type for e in all_events]
        assert EventType.SESSION_STARTED in event_types or EventType.TURN_STARTED in event_types
        assert EventType.ITEM_STARTED in event_types
        assert EventType.ITEM_DELTA in event_types
        assert EventType.ITEM_COMPLETED in event_types
