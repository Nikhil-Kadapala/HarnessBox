"""Tests for harnessbox.streaming — universal event schema + stream parser."""

from __future__ import annotations

import dataclasses

import pytest

from harnessbox.streaming import (
    EventType,
    ItemKind,
    ParserState,
    StreamParser,
    ToolKind,
    UniversalEvent,
    _ToolInfo,
    parse_line,
)

from ._streaming_helpers import _line, _stream_event

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
