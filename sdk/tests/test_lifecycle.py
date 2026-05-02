"""Tests for harnessbox.lifecycle — session state machine."""

import pytest

from harnessbox.lifecycle import (
    VALID_TRANSITIONS,
    InvalidTransitionError,
    SessionState,
    validate_transition,
)


class TestSessionState:
    def test_enum_values_match_strings(self) -> None:
        assert SessionState.BACKLOG.value == "backlog"
        assert SessionState.STARTING.value == "starting"
        assert SessionState.ACTIVE.value == "active"
        assert SessionState.PAUSED.value == "paused"
        assert SessionState.IN_REVIEW.value == "in_review"
        assert SessionState.ENDING.value == "ending"
        assert SessionState.MERGED.value == "merged"
        assert SessionState.FAILED.value == "failed"
        assert SessionState.ARCHIVED.value == "archived"

    def test_enum_from_string(self) -> None:
        assert SessionState("starting") is SessionState.STARTING
        assert SessionState("merged") is SessionState.MERGED
        assert SessionState("backlog") is SessionState.BACKLOG
        assert SessionState("in_review") is SessionState.IN_REVIEW
        assert SessionState("archived") is SessionState.ARCHIVED

    def test_all_states_in_transitions_map(self) -> None:
        for state in SessionState:
            assert state in VALID_TRANSITIONS


class TestValidTransitions:
    @pytest.mark.parametrize(
        "current,target",
        [
            (SessionState.BACKLOG, SessionState.STARTING),
            (SessionState.BACKLOG, SessionState.ARCHIVED),
            (SessionState.STARTING, SessionState.ACTIVE),
            (SessionState.STARTING, SessionState.FAILED),
            (SessionState.ACTIVE, SessionState.PAUSED),
            (SessionState.ACTIVE, SessionState.ENDING),
            (SessionState.ACTIVE, SessionState.IN_REVIEW),
            (SessionState.ACTIVE, SessionState.FAILED),
            (SessionState.PAUSED, SessionState.ACTIVE),
            (SessionState.PAUSED, SessionState.ENDING),
            (SessionState.PAUSED, SessionState.FAILED),
            (SessionState.IN_REVIEW, SessionState.ACTIVE),
            (SessionState.IN_REVIEW, SessionState.ENDING),
            (SessionState.IN_REVIEW, SessionState.MERGED),
            (SessionState.IN_REVIEW, SessionState.ARCHIVED),
            (SessionState.ENDING, SessionState.MERGED),
            (SessionState.ENDING, SessionState.FAILED),
            (SessionState.MERGED, SessionState.ARCHIVED),
            (SessionState.FAILED, SessionState.ARCHIVED),
        ],
    )
    def test_valid_transitions_return_true(
        self, current: SessionState, target: SessionState
    ) -> None:
        assert validate_transition(current, target) is True

    @pytest.mark.parametrize(
        "current,target",
        [
            (SessionState.BACKLOG, SessionState.ACTIVE),
            (SessionState.BACKLOG, SessionState.MERGED),
            (SessionState.STARTING, SessionState.MERGED),
            (SessionState.STARTING, SessionState.ENDING),
            (SessionState.ACTIVE, SessionState.STARTING),
            (SessionState.ACTIVE, SessionState.MERGED),
            (SessionState.ACTIVE, SessionState.ARCHIVED),
            (SessionState.PAUSED, SessionState.MERGED),
            (SessionState.PAUSED, SessionState.STARTING),
            (SessionState.IN_REVIEW, SessionState.STARTING),
            (SessionState.IN_REVIEW, SessionState.PAUSED),
            (SessionState.IN_REVIEW, SessionState.FAILED),
            (SessionState.ENDING, SessionState.ACTIVE),
            (SessionState.ENDING, SessionState.STARTING),
            (SessionState.MERGED, SessionState.ACTIVE),
            (SessionState.MERGED, SessionState.STARTING),
            (SessionState.FAILED, SessionState.ACTIVE),
            (SessionState.FAILED, SessionState.STARTING),
            (SessionState.ARCHIVED, SessionState.ACTIVE),
            (SessionState.ARCHIVED, SessionState.MERGED),
        ],
    )
    def test_invalid_transitions_return_false(
        self, current: SessionState, target: SessionState
    ) -> None:
        assert validate_transition(current, target) is False

    def test_terminal_states_have_no_outgoing(self) -> None:
        assert VALID_TRANSITIONS[SessionState.ARCHIVED] == frozenset()


class TestInvalidTransitionError:
    def test_message_includes_states(self) -> None:
        err = InvalidTransitionError(SessionState.STARTING, SessionState.MERGED)
        assert "starting" in str(err)
        assert "merged" in str(err)

    def test_attributes(self) -> None:
        err = InvalidTransitionError(SessionState.ACTIVE, SessionState.STARTING)
        assert err.current is SessionState.ACTIVE
        assert err.target is SessionState.STARTING
