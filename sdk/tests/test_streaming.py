"""Tests for harnessbox.streaming — universal event schema + stream parser."""

from __future__ import annotations

import json

from harnessbox.streaming import (
    EventType,
    ItemKind,
    ItemStatus,
    StreamParser,
    ToolKind,
    UniversalEvent,
    _ToolInfo,
    classify_tool,
    parse_stream_line,
)


def _line(**kwargs: object) -> str:
    return json.dumps(kwargs)


def _stream_event(event_type: str, **extra: object) -> str:
    return json.dumps({"type": "stream_event", "event": {"type": event_type, **extra}})


# ---------------------------------------------------------------------------
# System init → SESSION_STARTED
# ---------------------------------------------------------------------------


class TestSystemInit:
    def test_session_started(self) -> None:
        p = StreamParser()
        e = p.parse(_line(type="system", subtype="init", session_id="s-1", tools=["Bash", "Read"]))
        assert e is not None
        assert e.event_type == EventType.SESSION_STARTED
        assert e.session_id == "s-1"
        assert e.metadata["tools"] == ["Bash", "Read"]

    def test_non_init_system_ignored(self) -> None:
        p = StreamParser()
        assert p.parse(_line(type="system", subtype="heartbeat")) is None

    def test_session_id_tracked(self) -> None:
        p = StreamParser()
        p.parse(_line(type="system", subtype="init", session_id="s-1"))
        assert p.session_id == "s-1"


# ---------------------------------------------------------------------------
# Text blocks → ITEM_STARTED + ITEM_DELTA + ITEM_COMPLETED
# ---------------------------------------------------------------------------


class TestTextBlocks:
    def test_text_block_start(self) -> None:
        p = StreamParser()
        e = p.parse(_stream_event("content_block_start", content_block={"type": "text"}, index=0))
        assert e is not None
        assert e.event_type == EventType.ITEM_STARTED
        assert e.item_kind == ItemKind.MESSAGE
        assert e.item_status == ItemStatus.IN_PROGRESS

    def test_text_delta(self) -> None:
        p = StreamParser()
        p.parse(_stream_event("content_block_start", content_block={"type": "text"}, index=0))
        e = p.parse(
            _stream_event(
                "content_block_delta",
                delta={"type": "text_delta", "text": "hello"},
                index=0,
            )
        )
        assert e is not None
        assert e.event_type == EventType.ITEM_DELTA
        assert e.delta == "hello"
        assert e.item_kind == ItemKind.MESSAGE

    def test_text_block_stop(self) -> None:
        p = StreamParser()
        p.parse(_stream_event("content_block_start", content_block={"type": "text"}, index=0))
        e = p.parse(_stream_event("content_block_stop", index=0))
        assert e is not None
        assert e.event_type == EventType.ITEM_COMPLETED
        assert e.item_kind == ItemKind.MESSAGE
        assert e.item_status == ItemStatus.COMPLETED


# ---------------------------------------------------------------------------
# Thinking blocks → REASONING items
# ---------------------------------------------------------------------------


class TestThinkingBlocks:
    def test_thinking_block_start(self) -> None:
        p = StreamParser()
        e = p.parse(
            _stream_event("content_block_start", content_block={"type": "thinking"}, index=0)
        )
        assert e is not None
        assert e.event_type == EventType.ITEM_STARTED
        assert e.item_kind == ItemKind.REASONING

    def test_thinking_delta(self) -> None:
        p = StreamParser()
        p.parse(_stream_event("content_block_start", content_block={"type": "thinking"}, index=0))
        e = p.parse(
            _stream_event(
                "content_block_delta",
                delta={"type": "thinking_delta", "thinking": "let me think..."},
                index=0,
            )
        )
        assert e is not None
        assert e.event_type == EventType.ITEM_DELTA
        assert e.item_kind == ItemKind.REASONING
        assert e.delta == "let me think..."

    def test_thinking_block_stop(self) -> None:
        p = StreamParser()
        p.parse(_stream_event("content_block_start", content_block={"type": "thinking"}, index=0))
        e = p.parse(_stream_event("content_block_stop", index=0))
        assert e is not None
        assert e.event_type == EventType.ITEM_COMPLETED
        assert e.item_kind == ItemKind.REASONING


# ---------------------------------------------------------------------------
# Tool use blocks → TOOL_CALL items
# ---------------------------------------------------------------------------


class TestToolBlocks:
    def test_tool_start(self) -> None:
        p = StreamParser()
        e = p.parse(
            _stream_event(
                "content_block_start",
                content_block={"type": "tool_use", "name": "Bash", "id": "call-1"},
                index=0,
            )
        )
        assert e is not None
        assert e.event_type == EventType.ITEM_STARTED
        assert e.item_kind == ItemKind.TOOL_CALL
        assert e.tool_kind == ToolKind.BASH
        assert e.content[0].tool_name == "Bash"
        assert e.content[0].call_id == "call-1"

    def test_tool_input_delta(self) -> None:
        p = StreamParser()
        p.parse(
            _stream_event(
                "content_block_start",
                content_block={"type": "tool_use", "name": "Bash", "id": "call-1"},
                index=0,
            )
        )
        e = p.parse(
            _stream_event(
                "content_block_delta",
                delta={"type": "input_json_delta", "partial_json": '{"cmd":'},
                index=0,
            )
        )
        assert e is not None
        assert e.event_type == EventType.ITEM_DELTA
        assert e.item_kind == ItemKind.TOOL_CALL
        assert e.delta == '{"cmd":'
        assert e.tool_kind == ToolKind.BASH

    def test_tool_stop(self) -> None:
        p = StreamParser()
        p.parse(
            _stream_event(
                "content_block_start",
                content_block={"type": "tool_use", "name": "Read", "id": "call-2"},
                index=0,
            )
        )
        e = p.parse(_stream_event("content_block_stop", index=0))
        assert e is not None
        assert e.event_type == EventType.ITEM_COMPLETED
        assert e.item_kind == ItemKind.TOOL_CALL
        assert e.tool_kind == ToolKind.FILE_READ


# ---------------------------------------------------------------------------
# Tool results (from user messages)
# ---------------------------------------------------------------------------


class TestToolResults:
    def test_bash_tool_result(self) -> None:
        p = StreamParser()
        p._tool_map["call-1"] = _ToolInfo(name="Bash", input_buffer='{"command": "ls"}')
        results = p.parse_line(
            _line(
                type="user",
                message={
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "call-1",
                            "content": "file1.py\nfile2.py",
                        }
                    ]
                },
            )
        )
        assert len(results) == 1
        e = results[0]
        assert e.event_type == EventType.ITEM_COMPLETED
        assert e.item_kind == ItemKind.TOOL_RESULT
        assert e.tool_kind == ToolKind.BASH
        assert e.content[0].tool_input == "ls"

    def test_file_change_result(self) -> None:
        p = StreamParser()
        p._tool_map["call-2"] = _ToolInfo(
            name="Write", input_buffer='{"file_path": "/app/main.py"}'
        )
        results = p.parse_line(
            _line(
                type="user",
                message={
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "call-2",
                            "content": "File written",
                        }
                    ]
                },
            )
        )
        assert len(results) == 1
        e = results[0]
        assert e.tool_kind == ToolKind.FILE_CHANGE
        assert e.content[0].file_path == "/app/main.py"
        assert e.content[0].file_action == "write"

    def test_error_tool_result(self) -> None:
        p = StreamParser()
        p._tool_map["call-3"] = _ToolInfo(name="Bash", input_buffer="{}")
        results = p.parse_line(
            _line(
                type="user",
                message={
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "call-3",
                            "is_error": True,
                            "content": "command not found",
                        }
                    ]
                },
            )
        )
        assert len(results) == 1
        assert results[0].item_status == ItemStatus.FAILED


# ---------------------------------------------------------------------------
# Mixed content blocks
# ---------------------------------------------------------------------------


class TestMixedBlocks:
    def test_text_then_tool(self) -> None:
        p = StreamParser()
        p.parse(_stream_event("content_block_start", content_block={"type": "text"}, index=0))
        p.parse(
            _stream_event(
                "content_block_delta",
                delta={"type": "text_delta", "text": "I'll run"},
                index=0,
            )
        )
        p.parse(_stream_event("content_block_stop", index=0))

        e = p.parse(
            _stream_event(
                "content_block_start",
                content_block={"type": "tool_use", "name": "Bash", "id": "c-1"},
                index=1,
            )
        )
        assert e is not None
        assert e.event_type == EventType.ITEM_STARTED
        assert e.item_kind == ItemKind.TOOL_CALL


# ---------------------------------------------------------------------------
# Results and session end
# ---------------------------------------------------------------------------


class TestResults:
    def test_message_stop_is_turn_ended(self) -> None:
        p = StreamParser()
        e = p.parse(_stream_event("message_stop"))
        assert e is not None
        assert e.event_type == EventType.TURN_ENDED

    def test_assistant_message(self) -> None:
        p = StreamParser()
        e = p.parse(
            _line(
                type="assistant",
                session_id="sess-abc",
                message={"content": [{"type": "text", "text": "Done."}]},
            )
        )
        assert e is not None
        assert e.event_type == EventType.TURN_ENDED
        assert p.session_id == "sess-abc"

    def test_result_event(self) -> None:
        p = StreamParser()
        e = p.parse(
            _line(type="result", session_id="sess-xyz", duration_ms=3000, total_cost_usd=0.05)
        )
        assert e is not None
        assert e.event_type == EventType.SESSION_ENDED
        assert e.duration_ms == 3000
        assert e.cost_usd == 0.05

    def test_result_with_error(self) -> None:
        p = StreamParser()
        e = p.parse(_line(type="result", is_error=True, result="Rate limited", session_id="s-1"))
        assert e is not None
        assert e.event_type == EventType.SESSION_ENDED
        assert e.error_message == "Rate limited"

    def test_result_with_permission_denials(self) -> None:
        p = StreamParser()
        results = p.parse_line(
            _line(
                type="result",
                session_id="s-1",
                result={"permission_denials": [{"tool_name": "Bash"}]},
            )
        )
        assert len(results) == 2
        assert results[0].event_type == EventType.PERMISSION_REQUESTED
        assert results[0].metadata["tool"] == "Bash"
        assert results[1].event_type == EventType.SESSION_ENDED

    def test_process_error(self) -> None:
        p = StreamParser()
        e = p.parse(_line(type="_process_error", exit_code=1, stderr="boom"))
        assert e is not None
        assert e.event_type == EventType.ERROR
        assert e.error_message == "boom"


# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Event schema
# ---------------------------------------------------------------------------


class TestUniversalEvent:
    def test_to_dict(self) -> None:
        e = UniversalEvent(
            event_id="e-1",
            sequence=1,
            timestamp="2026-01-01T00:00:00Z",
            session_id="s-1",
            event_type=EventType.ITEM_DELTA,
            delta="hello",
            item_kind=ItemKind.MESSAGE,
        )
        d = e.to_dict()
        assert d["event_type"] == "item.delta"
        assert d["delta"] == "hello"
        assert d["item_kind"] == "message"
        assert "cost_usd" not in d

    def test_sequence_increments(self) -> None:
        p = StreamParser()
        e1 = p.parse(_stream_event("content_block_start", content_block={"type": "text"}, index=0))
        e2 = p.parse(
            _stream_event(
                "content_block_delta",
                delta={"type": "text_delta", "text": "a"},
                index=0,
            )
        )
        assert e1 is not None and e2 is not None
        assert e2.sequence > e1.sequence


# ---------------------------------------------------------------------------
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
