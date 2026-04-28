"""Session lifecycle state machine for sandboxed agent sessions."""

from __future__ import annotations

from enum import Enum


class SessionState(str, Enum):
    STARTING = "starting"
    ACTIVE = "active"
    PAUSED = "paused"
    ENDING = "ending"
    MERGED = "merged"
    FAILED = "failed"


VALID_TRANSITIONS: dict[SessionState, frozenset[SessionState]] = {
    SessionState.STARTING: frozenset({SessionState.ACTIVE, SessionState.FAILED}),
    SessionState.ACTIVE: frozenset({SessionState.PAUSED, SessionState.ENDING, SessionState.FAILED}),
    SessionState.PAUSED: frozenset({SessionState.ACTIVE, SessionState.ENDING, SessionState.FAILED}),
    SessionState.ENDING: frozenset({SessionState.MERGED, SessionState.FAILED}),
    SessionState.MERGED: frozenset(),
    SessionState.FAILED: frozenset(),
}


class InvalidTransitionError(Exception):
    """Raised when a state transition is not allowed."""

    def __init__(self, current: SessionState, target: SessionState) -> None:
        self.current = current
        self.target = target
        super().__init__(f"Invalid transition: {current.value!r} → {target.value!r}")


def validate_transition(current: SessionState, target: SessionState) -> bool:
    """Return True if the transition from *current* to *target* is allowed."""
    return target in VALID_TRANSITIONS.get(current, frozenset())
