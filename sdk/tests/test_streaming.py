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

    def test_agent_tool_stop_includes_subagent_metadata(self) -> None:
        p = StreamParser()
        p.parse(
            _stream_event(
                "content_block_start",
                content_block={"type": "tool_use", "name": "Agent", "id": "call-agent-1"},
                index=0,
            )
        )
        p.parse(
            _stream_event(
                "content_block_delta",
                delta={
                    "type": "input_json_delta",
                    "partial_json": json.dumps({
                        "subagent_type": "code-reviewer",
                        "description": "Security audit",
                        "prompt": "Review auth.py",
                    }),
                },
                index=0,
            )
        )
        e = p.parse(_stream_event("content_block_stop", index=0))
        assert e is not None
        assert e.event_type == EventType.ITEM_COMPLETED
        assert e.tool_kind == ToolKind.AGENT
        assert e.metadata["subagent_type"] == "code-reviewer"
        assert e.metadata["description"] == "Security audit"
        assert e.metadata["prompt"] == "Review auth.py"


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


# ---------------------------------------------------------------------------
# System api_retry → API_RETRY
# ---------------------------------------------------------------------------


class TestSystemApiRetry:
    def test_api_retry_event(self) -> None:
        p = StreamParser()
        e = p.parse(
            _line(
                type="system",
                subtype="api_retry",
                attempt=1,
                max_retries=3,
                retry_delay_ms=2000,
                error_status=529,
                error="rate_limit",
            )
        )
        assert e is not None
        assert e.event_type == EventType.API_RETRY
        assert e.metadata["attempt"] == 1
        assert e.metadata["max_retries"] == 3
        assert e.metadata["retry_delay_ms"] == 2000
        assert e.metadata["error_status"] == 529
        assert e.metadata["error"] == "rate_limit"

    def test_api_retry_partial_fields(self) -> None:
        p = StreamParser()
        e = p.parse(
            _line(type="system", subtype="api_retry", attempt=2, error="server_error")
        )
        assert e is not None
        assert e.event_type == EventType.API_RETRY
        assert e.metadata["attempt"] == 2
        assert e.metadata["max_retries"] is None
        assert e.metadata["retry_delay_ms"] is None

    def test_api_retry_does_not_increment_turn_count(self) -> None:
        p = StreamParser()
        p.parse(_line(type="system", subtype="init", session_id="s-1"))
        p.parse(_line(type="system", subtype="api_retry", attempt=1))
        e = p.parse(_line(type="system", subtype="init", session_id="s-1"))
        assert e is not None
        assert e.metadata["turn"] == 2


# ---------------------------------------------------------------------------
# Enriched result metadata
# ---------------------------------------------------------------------------


class TestEnrichedResult:
    def test_result_includes_usage_cache_fields(self) -> None:
        p = StreamParser()
        e = p.parse(
            _line(
                type="result",
                session_id="s-1",
                total_cost_usd=0.05,
                duration_ms=5000,
                usage={
                    "input_tokens": 3200,
                    "output_tokens": 480,
                    "cache_read_input_tokens": 1800,
                    "cache_creation_input_tokens": 400,
                },
            )
        )
        assert e is not None
        assert e.metadata["usage"]["input_tokens"] == 3200
        assert e.metadata["usage"]["output_tokens"] == 480
        assert e.metadata["usage"]["cache_read_input_tokens"] == 1800
        assert e.metadata["usage"]["cache_creation_input_tokens"] == 400

    def test_result_includes_model_usage(self) -> None:
        p = StreamParser()
        e = p.parse(
            _line(
                type="result",
                session_id="s-1",
                total_cost_usd=0.05,
                duration_ms=3000,
                modelUsage={"claude-sonnet-4-5": {"inputTokens": 100, "outputTokens": 50}},
            )
        )
        assert e is not None
        assert e.metadata["model_usage"] == {
            "claude-sonnet-4-5": {"inputTokens": 100, "outputTokens": 50}
        }

    def test_result_includes_num_turns_and_duration_api(self) -> None:
        p = StreamParser()
        e = p.parse(
            _line(
                type="result",
                session_id="s-1",
                total_cost_usd=0.01,
                duration_ms=5000,
                duration_api_ms=3000,
                num_turns=4,
            )
        )
        assert e is not None
        assert e.metadata["num_turns"] == 4
        assert e.metadata["duration_api_ms"] == 3000

    def test_result_without_enrichment_fields(self) -> None:
        p = StreamParser()
        e = p.parse(_line(type="result", session_id="s-1", total_cost_usd=0.01, duration_ms=1000))
        assert e is not None
        assert "usage" not in e.metadata
        assert "model_usage" not in e.metadata
        assert "num_turns" not in e.metadata

    def test_result_empty_model_usage_not_included(self) -> None:
        p = StreamParser()
        e = p.parse(
            _line(type="result", session_id="s-1", total_cost_usd=0.01, modelUsage={})
        )
        assert e is not None
        assert "model_usage" not in e.metadata


# ---------------------------------------------------------------------------
# Control requests — AskUserQuestion → INPUT_REQUESTED
# ---------------------------------------------------------------------------


class TestInputRequested:
    def test_ask_user_question_emits_input_requested(self) -> None:
        p = StreamParser()
        events = p.parse_line(
            _line(
                type="control_request",
                request_id="req-1",
                request={
                    "subtype": "tool_use",
                    "tool_name": "AskUserQuestion",
                    "input": {
                        "questions": [
                            {
                                "header": "Database",
                                "question": "Which database?",
                                "options": [
                                    {"label": "PostgreSQL", "description": "Relational"},
                                    {"label": "MongoDB", "description": "Document-based"},
                                ],
                                "multiSelect": False,
                            }
                        ]
                    },
                },
            )
        )
        assert len(events) == 1
        e = events[0]
        assert e.event_type == EventType.INPUT_REQUESTED
        assert e.metadata["request_id"] == "req-1"
        assert len(e.metadata["questions"]) == 1
        assert e.metadata["questions"][0]["header"] == "Database"
        assert len(e.metadata["questions"][0]["options"]) == 2

    def test_regular_tool_permission_still_emits_permission_requested(self) -> None:
        p = StreamParser()
        events = p.parse_line(
            _line(
                type="control_request",
                request_id="req-2",
                request={
                    "subtype": "tool_use",
                    "tool_name": "Bash",
                    "input": {"command": "rm -rf /"},
                },
            )
        )
        assert len(events) == 1
        assert events[0].event_type == EventType.PERMISSION_REQUESTED
        assert events[0].metadata["tool_name"] == "Bash"

    def test_ask_user_question_with_empty_input(self) -> None:
        p = StreamParser()
        events = p.parse_line(
            _line(
                type="control_request",
                request_id="req-3",
                request={
                    "subtype": "tool_use",
                    "tool_name": "AskUserQuestion",
                    "input": {},
                },
            )
        )
        assert len(events) == 1
        assert events[0].event_type == EventType.INPUT_REQUESTED
        assert events[0].metadata["questions"] == []
