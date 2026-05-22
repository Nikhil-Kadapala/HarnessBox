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
