"""Tests for harnessbox.lifecycle — session state machine."""

import pytest

from harnessbox.lifecycle import (
    VALID_TRANSITIONS,
    InvalidTransitionError,
    WorkspaceState,
    validate_transition,
)


class TestWorkspaceState:
    def test_enum_values_match_strings(self) -> None:
        assert WorkspaceState.BACKLOG.value == "backlog"
        assert WorkspaceState.STARTING.value == "starting"
        assert WorkspaceState.ACTIVE.value == "active"
        assert WorkspaceState.PAUSED.value == "paused"
        assert WorkspaceState.IN_REVIEW.value == "in_review"
        assert WorkspaceState.ENDING.value == "ending"
        assert WorkspaceState.MERGED.value == "merged"
        assert WorkspaceState.FAILED.value == "failed"
        assert WorkspaceState.ARCHIVED.value == "archived"

    def test_enum_from_string(self) -> None:
        assert WorkspaceState("starting") is WorkspaceState.STARTING
        assert WorkspaceState("merged") is WorkspaceState.MERGED
        assert WorkspaceState("backlog") is WorkspaceState.BACKLOG
        assert WorkspaceState("in_review") is WorkspaceState.IN_REVIEW
        assert WorkspaceState("archived") is WorkspaceState.ARCHIVED

    def test_all_states_in_transitions_map(self) -> None:
        for state in WorkspaceState:
            assert state in VALID_TRANSITIONS


class TestValidTransitions:
    @pytest.mark.parametrize(
        "current,target",
        [
            (WorkspaceState.BACKLOG, WorkspaceState.STARTING),
            (WorkspaceState.BACKLOG, WorkspaceState.ARCHIVED),
            (WorkspaceState.STARTING, WorkspaceState.ACTIVE),
            (WorkspaceState.STARTING, WorkspaceState.FAILED),
            (WorkspaceState.ACTIVE, WorkspaceState.PAUSED),
            (WorkspaceState.ACTIVE, WorkspaceState.ENDING),
            (WorkspaceState.ACTIVE, WorkspaceState.IN_REVIEW),
            (WorkspaceState.ACTIVE, WorkspaceState.FAILED),
            (WorkspaceState.PAUSED, WorkspaceState.ACTIVE),
            (WorkspaceState.PAUSED, WorkspaceState.ENDING),
            (WorkspaceState.PAUSED, WorkspaceState.FAILED),
            (WorkspaceState.IN_REVIEW, WorkspaceState.ACTIVE),
            (WorkspaceState.IN_REVIEW, WorkspaceState.ENDING),
            (WorkspaceState.IN_REVIEW, WorkspaceState.MERGED),
            (WorkspaceState.IN_REVIEW, WorkspaceState.ARCHIVED),
            (WorkspaceState.ENDING, WorkspaceState.MERGED),
            (WorkspaceState.ENDING, WorkspaceState.FAILED),
            (WorkspaceState.MERGED, WorkspaceState.ARCHIVED),
            (WorkspaceState.FAILED, WorkspaceState.ARCHIVED),
        ],
    )
    def test_valid_transitions_return_true(
        self, current: WorkspaceState, target: WorkspaceState
    ) -> None:
        assert validate_transition(current, target) is True

    @pytest.mark.parametrize(
        "current,target",
        [
            (WorkspaceState.BACKLOG, WorkspaceState.ACTIVE),
            (WorkspaceState.BACKLOG, WorkspaceState.MERGED),
            (WorkspaceState.STARTING, WorkspaceState.MERGED),
            (WorkspaceState.STARTING, WorkspaceState.ENDING),
            (WorkspaceState.ACTIVE, WorkspaceState.STARTING),
            (WorkspaceState.ACTIVE, WorkspaceState.MERGED),
            (WorkspaceState.ACTIVE, WorkspaceState.ARCHIVED),
            (WorkspaceState.PAUSED, WorkspaceState.MERGED),
            (WorkspaceState.PAUSED, WorkspaceState.STARTING),
            (WorkspaceState.IN_REVIEW, WorkspaceState.STARTING),
            (WorkspaceState.IN_REVIEW, WorkspaceState.PAUSED),
            (WorkspaceState.IN_REVIEW, WorkspaceState.FAILED),
            (WorkspaceState.ENDING, WorkspaceState.ACTIVE),
            (WorkspaceState.ENDING, WorkspaceState.STARTING),
            (WorkspaceState.MERGED, WorkspaceState.ACTIVE),
            (WorkspaceState.MERGED, WorkspaceState.STARTING),
            (WorkspaceState.FAILED, WorkspaceState.ACTIVE),
            (WorkspaceState.FAILED, WorkspaceState.STARTING),
            (WorkspaceState.ARCHIVED, WorkspaceState.ACTIVE),
            (WorkspaceState.ARCHIVED, WorkspaceState.MERGED),
        ],
    )
    def test_invalid_transitions_return_false(
        self, current: WorkspaceState, target: WorkspaceState
    ) -> None:
        assert validate_transition(current, target) is False

    def test_terminal_states_have_no_outgoing(self) -> None:
        assert VALID_TRANSITIONS[WorkspaceState.ARCHIVED] == frozenset()


class TestInvalidTransitionError:
    def test_message_includes_states(self) -> None:
        err = InvalidTransitionError(WorkspaceState.STARTING, WorkspaceState.MERGED)
        assert "starting" in str(err)
        assert "merged" in str(err)

    def test_attributes(self) -> None:
        err = InvalidTransitionError(WorkspaceState.ACTIVE, WorkspaceState.STARTING)
        assert err.current is WorkspaceState.ACTIVE
        assert err.target is WorkspaceState.STARTING
