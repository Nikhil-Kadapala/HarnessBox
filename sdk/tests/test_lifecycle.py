"""Tests for harnessbox.lifecycle — runtime and workflow state machines."""

import pytest

from harnessbox.lifecycle import (
    VALID_RUNTIME_TRANSITIONS,
    VALID_WORKFLOW_TRANSITIONS,
    InvalidTransitionError,
    RuntimeState,
    WorkflowState,
    validate_runtime_transition,
    validate_workflow_transition,
)


class TestRuntimeState:
    def test_enum_values_match_strings(self) -> None:
        assert RuntimeState.STARTING.value == "starting"
        assert RuntimeState.ACTIVE.value == "active"
        assert RuntimeState.PAUSED.value == "paused"
        assert RuntimeState.ENDING.value == "ending"
        assert RuntimeState.ENDED.value == "ended"
        assert RuntimeState.FAILED.value == "failed"

    def test_enum_from_string(self) -> None:
        assert RuntimeState("starting") is RuntimeState.STARTING
        assert RuntimeState("active") is RuntimeState.ACTIVE
        assert RuntimeState("ended") is RuntimeState.ENDED

    def test_all_states_in_transitions_map(self) -> None:
        for state in RuntimeState:
            assert state in VALID_RUNTIME_TRANSITIONS


class TestWorkflowState:
    def test_enum_values_match_strings(self) -> None:
        assert WorkflowState.BACKLOG.value == "backlog"
        assert WorkflowState.IN_PROGRESS.value == "in_progress"
        assert WorkflowState.IN_REVIEW.value == "in_review"
        assert WorkflowState.MERGED.value == "merged"
        assert WorkflowState.ARCHIVED.value == "archived"

    def test_enum_from_string(self) -> None:
        assert WorkflowState("backlog") is WorkflowState.BACKLOG
        assert WorkflowState("in_review") is WorkflowState.IN_REVIEW
        assert WorkflowState("archived") is WorkflowState.ARCHIVED

    def test_all_states_in_transitions_map(self) -> None:
        for state in WorkflowState:
            assert state in VALID_WORKFLOW_TRANSITIONS


class TestRuntimeTransitions:
    @pytest.mark.parametrize(
        "current,target",
        [
            (RuntimeState.STARTING, RuntimeState.ACTIVE),
            (RuntimeState.STARTING, RuntimeState.FAILED),
            (RuntimeState.ACTIVE, RuntimeState.PAUSED),
            (RuntimeState.ACTIVE, RuntimeState.ENDING),
            (RuntimeState.ACTIVE, RuntimeState.FAILED),
            (RuntimeState.PAUSED, RuntimeState.ACTIVE),
            (RuntimeState.PAUSED, RuntimeState.ENDING),
            (RuntimeState.PAUSED, RuntimeState.FAILED),
            (RuntimeState.ENDING, RuntimeState.ENDED),
            (RuntimeState.ENDING, RuntimeState.FAILED),
        ],
    )
    def test_valid_transitions_return_true(
        self, current: RuntimeState, target: RuntimeState
    ) -> None:
        assert validate_runtime_transition(current, target) is True

    @pytest.mark.parametrize(
        "current,target",
        [
            (RuntimeState.STARTING, RuntimeState.ENDING),
            (RuntimeState.STARTING, RuntimeState.PAUSED),
            (RuntimeState.ACTIVE, RuntimeState.STARTING),
            (RuntimeState.PAUSED, RuntimeState.STARTING),
            (RuntimeState.ENDING, RuntimeState.ACTIVE),
            (RuntimeState.ENDING, RuntimeState.STARTING),
            (RuntimeState.ENDED, RuntimeState.ACTIVE),
            (RuntimeState.ENDED, RuntimeState.STARTING),
            (RuntimeState.FAILED, RuntimeState.ACTIVE),
            (RuntimeState.FAILED, RuntimeState.STARTING),
        ],
    )
    def test_invalid_transitions_return_false(
        self, current: RuntimeState, target: RuntimeState
    ) -> None:
        assert validate_runtime_transition(current, target) is False

    def test_terminal_states_have_no_outgoing(self) -> None:
        assert VALID_RUNTIME_TRANSITIONS[RuntimeState.ENDED] == frozenset()
        assert VALID_RUNTIME_TRANSITIONS[RuntimeState.FAILED] == frozenset()


class TestWorkflowTransitions:
    @pytest.mark.parametrize(
        "current,target",
        [
            (WorkflowState.BACKLOG, WorkflowState.IN_PROGRESS),
            (WorkflowState.BACKLOG, WorkflowState.ARCHIVED),
            (WorkflowState.IN_PROGRESS, WorkflowState.IN_REVIEW),
            (WorkflowState.IN_PROGRESS, WorkflowState.ARCHIVED),
            (WorkflowState.IN_REVIEW, WorkflowState.IN_PROGRESS),
            (WorkflowState.IN_REVIEW, WorkflowState.MERGED),
            (WorkflowState.IN_REVIEW, WorkflowState.ARCHIVED),
            (WorkflowState.MERGED, WorkflowState.ARCHIVED),
        ],
    )
    def test_valid_transitions_return_true(
        self, current: WorkflowState, target: WorkflowState
    ) -> None:
        assert validate_workflow_transition(current, target) is True

    @pytest.mark.parametrize(
        "current,target",
        [
            (WorkflowState.BACKLOG, WorkflowState.MERGED),
            (WorkflowState.BACKLOG, WorkflowState.IN_REVIEW),
            (WorkflowState.IN_PROGRESS, WorkflowState.MERGED),
            (WorkflowState.IN_PROGRESS, WorkflowState.BACKLOG),
            (WorkflowState.IN_REVIEW, WorkflowState.BACKLOG),
            (WorkflowState.MERGED, WorkflowState.IN_PROGRESS),
            (WorkflowState.MERGED, WorkflowState.IN_REVIEW),
            (WorkflowState.ARCHIVED, WorkflowState.IN_PROGRESS),
            (WorkflowState.ARCHIVED, WorkflowState.MERGED),
        ],
    )
    def test_invalid_transitions_return_false(
        self, current: WorkflowState, target: WorkflowState
    ) -> None:
        assert validate_workflow_transition(current, target) is False

    def test_archived_is_terminal(self) -> None:
        assert VALID_WORKFLOW_TRANSITIONS[WorkflowState.ARCHIVED] == frozenset()


class TestInvalidTransitionError:
    def test_message_includes_states(self) -> None:
        err = InvalidTransitionError(RuntimeState.STARTING, RuntimeState.ENDING)
        assert "starting" in str(err)
        assert "ending" in str(err)

    def test_attributes(self) -> None:
        err = InvalidTransitionError(RuntimeState.ACTIVE, RuntimeState.STARTING)
        assert err.current is RuntimeState.ACTIVE
        assert err.target is RuntimeState.STARTING

    def test_workflow_error(self) -> None:
        err = InvalidTransitionError(WorkflowState.BACKLOG, WorkflowState.MERGED)
        assert "backlog" in str(err)
        assert "merged" in str(err)
