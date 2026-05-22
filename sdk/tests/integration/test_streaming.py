"""Tests for harnessbox.streaming — universal event schema + stream parser."""

from __future__ import annotations

import dataclasses
import json

import pytest

from harnessbox.streaming import (
    EventType,
    ItemKind,
    ItemStatus,
    ParserState,
    StreamParser,
    ToolKind,
    UniversalEvent,
    _ToolInfo,
    classify_tool,
    parse_line,
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
                    "partial_json": json.dumps(
                        {
                            "subagent_type": "code-reviewer",
                            "description": "Security audit",
                            "prompt": "Review auth.py",
                        }
                    ),
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
        p.tool_map = {"call-1": _ToolInfo(name="Bash", input_buffer='{"command": "ls"}')}
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
        p.tool_map = {
            "call-2": _ToolInfo(name="Write", input_buffer='{"file_path": "/app/main.py"}')
        }
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
        p.tool_map = {"call-3": _ToolInfo(name="Bash", input_buffer="{}")}
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
    def test_message_stop_suppressed(self) -> None:
        p = StreamParser()
        p.parse(_stream_event("content_block_start", content_block={"type": "text"}, index=0))
        e = p.parse(_stream_event("message_stop"))
        assert e is None
        assert p.state.turn_active is False
        assert p.state.active_blocks == {}

    def test_assistant_message_suppressed(self) -> None:
        p = StreamParser(session_id="init-id")
        e = p.parse(
            _line(
                type="assistant",
                session_id="sess-abc",
                message={"content": [{"type": "text", "text": "Done."}]},
            )
        )
        assert e is None
        assert p.session_id == "init-id"

    def test_assistant_updates_tool_map(self) -> None:
        p = StreamParser()
        p.parse(
            _line(
                type="assistant",
                session_id="sess-abc",
                message={
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "call-1",
                            "name": "Bash",
                            "input": {"command": "ls"},
                        }
                    ]
                },
            )
        )
        assert "call-1" in p.tool_map
        assert p.tool_map["call-1"].name == "Bash"

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
        e = p.parse(_line(type="system", subtype="api_retry", attempt=2, error="server_error"))
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
        e = p.parse(_line(type="result", session_id="s-1", total_cost_usd=0.01, modelUsage={}))
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


# ---------------------------------------------------------------------------
# ParserState value object — direct state construction tests
# ---------------------------------------------------------------------------


class TestParserState:
    def test_default_state(self) -> None:
        state = ParserState()
        assert state.session_id == ""
        assert state.sequence == 0
        assert state.tool_map == {}
        assert state.active_blocks == {}
        assert state.turn_active is False
        assert state.persistent is False
        assert state.turn_count == 0

    def test_state_is_frozen(self) -> None:
        state = ParserState()
        with pytest.raises(dataclasses.FrozenInstanceError):
            state.session_id = "x"  # type: ignore[misc]

    def test_tool_result_from_prebuilt_state(self) -> None:
        """Reproduce a tool_result parse with a pre-seeded tool_map — no replay needed."""
        state = ParserState(
            session_id="s-test",
            sequence=10,
            tool_map={"call-99": _ToolInfo(name="Bash", input_buffer='{"command": "echo hi"}')},
        )
        new_state, events = parse_line(
            state,
            _line(
                type="user",
                message={
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "call-99",
                            "content": "hi",
                        }
                    ]
                },
            ),
        )
        assert len(events) == 1
        assert events[0].event_type == EventType.ITEM_COMPLETED
        assert events[0].item_kind == ItemKind.TOOL_RESULT
        assert events[0].tool_kind == ToolKind.BASH
        assert events[0].content[0].tool_input == "echo hi"
        assert events[0].sequence == 11
        assert new_state.sequence == 11

    def test_block_delta_from_prebuilt_active_blocks(self) -> None:
        """Hit a specific delta branch by constructing active_blocks directly."""
        state = ParserState(
            session_id="s-1",
            sequence=5,
            active_blocks={0: {"type": "text", "item_id": "item-abc"}},
            turn_active=True,
        )
        new_state, events = parse_line(
            state,
            _stream_event(
                "content_block_delta",
                delta={"type": "text_delta", "text": "world"},
                index=0,
            ),
        )
        assert len(events) == 1
        assert events[0].delta == "world"
        assert events[0].item_id == "item-abc"
        assert new_state.sequence == 6

    def test_persistent_mode_second_init_is_turn_started(self) -> None:
        """Verify persistent mode behavior with pre-set turn_count."""
        state = ParserState(persistent=True, turn_count=1)
        new_state, events = parse_line(
            state, _line(type="system", subtype="init", session_id="s-2", tools=[])
        )
        assert len(events) == 1
        assert events[0].event_type == EventType.TURN_STARTED
        assert new_state.turn_count == 2

    def test_state_unchanged_on_unparseable_line(self) -> None:
        state = ParserState(session_id="s-1", sequence=5)
        new_state, events = parse_line(state, "not json {{{")
        assert events == []
        assert new_state is state

    def test_input_buffer_accumulates_across_deltas(self) -> None:
        """Verify tool input buffer grows immutably across delta calls."""
        state = ParserState(
            session_id="s-1",
            active_blocks={0: {"type": "tool_use", "id": "call-1", "item_id": "call-1"}},
            tool_map={"call-1": _ToolInfo(name="Bash")},
            turn_active=True,
        )
        state, events1 = parse_line(
            state,
            _stream_event(
                "content_block_delta",
                delta={"type": "input_json_delta", "partial_json": '{"com'},
                index=0,
            ),
        )
        state, events2 = parse_line(
            state,
            _stream_event(
                "content_block_delta",
                delta={"type": "input_json_delta", "partial_json": 'mand": "ls"}'},
                index=0,
            ),
        )
        assert state.tool_map["call-1"].input_buffer == '{"command": "ls"}'
        assert len(events1) == 1
        assert len(events2) == 1

    def test_streamer_exposes_state(self) -> None:
        """StreamParser.state returns the current ParserState."""
        p = StreamParser(session_id="s-1")
        assert p.state.session_id == "s-1"
        p.parse(_line(type="system", subtype="init", session_id="s-2", tools=[]))
        assert p.state.session_id == "s-2"
        assert p.state.turn_count == 1


# ---------------------------------------------------------------------------
# Session ID stability and single TURN_ENDED invariants
# ---------------------------------------------------------------------------


class TestSessionIdStability:
    def test_session_id_precedence_in_result(self) -> None:
        """state.session_id is preserved over result's session_id."""
        state = ParserState(session_id="init-id", sequence=5)
        new_state, events = parse_line(
            state,
            _line(type="result", session_id="api-uuid", duration_ms=100, total_cost_usd=0.01),
        )
        assert len(events) == 1
        assert events[0].session_id == "init-id"
        assert new_state.session_id == "init-id"

    def test_session_id_fallback_when_state_empty(self) -> None:
        """When state has no session_id, result's session_id is used."""
        state = ParserState(session_id="", sequence=0)
        new_state, events = parse_line(
            state,
            _line(type="result", session_id="from-result", duration_ms=50, total_cost_usd=0.02),
        )
        assert len(events) == 1
        assert events[0].session_id == "from-result"
        assert new_state.session_id == "from-result"

    def test_session_id_stable_across_full_turn(self) -> None:
        """session_id from init is not overwritten by assistant or result."""
        p = StreamParser(persistent=True)
        p.parse(_line(type="system", subtype="init", session_id="init-id", tools=[]))
        assert p.session_id == "init-id"

        p.parse(
            _line(
                type="assistant",
                session_id="api-uuid",
                message={"content": [{"type": "text", "text": "hi"}]},
            )
        )
        assert p.session_id == "init-id"

        events = p.parse_line(
            _line(
                type="result",
                session_id="api-uuid",
                duration_ms=1000,
                total_cost_usd=0.05,
            )
        )
        assert p.session_id == "init-id"
        assert events[0].session_id == "init-id"


class TestSingleTurnEnded:
    def test_full_turn_produces_one_turn_ended(self) -> None:
        """A full persistent-mode turn emits exactly 1 TURN_ENDED (from result)."""
        p = StreamParser(persistent=True)
        all_events: list[UniversalEvent] = []

        all_events.extend(
            p.parse_line(_line(type="system", subtype="init", session_id="s-1", tools=[]))
        )
        all_events.extend(
            p.parse_line(
                _stream_event("content_block_start", content_block={"type": "text"}, index=0)
            )
        )
        all_events.extend(
            p.parse_line(
                _stream_event(
                    "content_block_delta", delta={"type": "text_delta", "text": "hello"}, index=0
                )
            )
        )
        all_events.extend(
            p.parse_line(
                _line(
                    type="assistant",
                    session_id="api-uuid",
                    message={"content": [{"type": "text", "text": "hello"}]},
                )
            )
        )
        all_events.extend(p.parse_line(_stream_event("content_block_stop", index=0)))
        all_events.extend(p.parse_line(_stream_event("message_stop")))
        all_events.extend(
            p.parse_line(
                _line(
                    type="result",
                    session_id="api-uuid",
                    duration_ms=2000,
                    total_cost_usd=0.10,
                )
            )
        )

        turn_ended = [e for e in all_events if e.event_type == EventType.TURN_ENDED]
        assert len(turn_ended) == 1
        assert turn_ended[0].cost_usd == 0.10
        assert turn_ended[0].duration_ms == 2000
        assert turn_ended[0].session_id == "s-1"


# ---------------------------------------------------------------------------
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
