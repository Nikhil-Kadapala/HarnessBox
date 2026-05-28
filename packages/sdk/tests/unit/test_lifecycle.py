"""Tests for harnessbox.lifecycle — runtime state machine."""

import pytest

from harnessbox.lifecycle import (
    VALID_RUNTIME_TRANSITIONS,
    InvalidTransitionError,
    RuntimeState,
    validate_runtime_transition,
)


class TestRuntimeState:
    def test_enum_values_match_strings(self) -> None:
        assert RuntimeState.STARTING.value == "starting"
        assert RuntimeState.ACTIVE.value == "active"
        assert RuntimeState.PAUSED.value == "paused"
        assert RuntimeState.DYING.value == "dying"
        assert RuntimeState.ENDED.value == "ended"
        assert RuntimeState.DEAD.value == "dead"

    def test_enum_from_string(self) -> None:
        assert RuntimeState("starting") is RuntimeState.STARTING
        assert RuntimeState("active") is RuntimeState.ACTIVE
        assert RuntimeState("ended") is RuntimeState.ENDED

    def test_all_states_in_transitions_map(self) -> None:
        for state in RuntimeState:
            assert state in VALID_RUNTIME_TRANSITIONS


class TestRuntimeTransitions:
    @pytest.mark.parametrize(
        "current,target",
        [
            (RuntimeState.STARTING, RuntimeState.ACTIVE),
            (RuntimeState.STARTING, RuntimeState.DEAD),
            (RuntimeState.ACTIVE, RuntimeState.PAUSED),
            (RuntimeState.ACTIVE, RuntimeState.DYING),
            (RuntimeState.ACTIVE, RuntimeState.DEAD),
            (RuntimeState.PAUSED, RuntimeState.ACTIVE),
            (RuntimeState.PAUSED, RuntimeState.DYING),
            (RuntimeState.PAUSED, RuntimeState.DEAD),
            (RuntimeState.DYING, RuntimeState.ENDED),
            (RuntimeState.DYING, RuntimeState.DEAD),
        ],
    )
    def test_valid_transitions_return_true(
        self, current: RuntimeState, target: RuntimeState
    ) -> None:
        assert validate_runtime_transition(current, target) is True

    @pytest.mark.parametrize(
        "current,target",
        [
            (RuntimeState.STARTING, RuntimeState.DYING),
            (RuntimeState.STARTING, RuntimeState.PAUSED),
            (RuntimeState.ACTIVE, RuntimeState.STARTING),
            (RuntimeState.PAUSED, RuntimeState.STARTING),
            (RuntimeState.DYING, RuntimeState.ACTIVE),
            (RuntimeState.DYING, RuntimeState.STARTING),
            (RuntimeState.ENDED, RuntimeState.ACTIVE),
            (RuntimeState.ENDED, RuntimeState.STARTING),
            (RuntimeState.DEAD, RuntimeState.ACTIVE),
            (RuntimeState.DEAD, RuntimeState.STARTING),
        ],
    )
    def test_invalid_transitions_return_false(
        self, current: RuntimeState, target: RuntimeState
    ) -> None:
        assert validate_runtime_transition(current, target) is False

    def test_terminal_states_have_no_outgoing(self) -> None:
        assert VALID_RUNTIME_TRANSITIONS[RuntimeState.ENDED] == frozenset()
        assert VALID_RUNTIME_TRANSITIONS[RuntimeState.DEAD] == frozenset()


class TestInvalidTransitionError:
    def test_message_includes_states(self) -> None:
        err = InvalidTransitionError(RuntimeState.STARTING, RuntimeState.DYING)
        assert "starting" in str(err)
        assert "dying" in str(err)

    def test_attributes(self) -> None:
        err = InvalidTransitionError(RuntimeState.ACTIVE, RuntimeState.STARTING)
        assert err.current is RuntimeState.ACTIVE
        assert err.target is RuntimeState.STARTING
