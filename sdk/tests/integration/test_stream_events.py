"""Tests for harnessbox.streaming — universal event schema + stream parser."""

from __future__ import annotations

from harnessbox.streaming import (
    EventType,
    ItemKind,
    StreamParser,
    UniversalEvent,
)

from ._streaming_helpers import _line, _stream_event

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
