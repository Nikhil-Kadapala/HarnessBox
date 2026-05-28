"""Workspace lifecycle state machine for sandboxed workspaces.

RuntimeState tracks sandbox infrastructure (is the VM running?).
"""

from __future__ import annotations

from enum import Enum


class SessionStatus(str, Enum):
    """User-facing session status.

    Users see only three states:
    - RUNNING: actively doing work, accepting prompts
    - SLEEPING: paused to save cost, wakes transparently on next interaction
    - KILLED: user explicitly destroyed it, gone forever
    """

    RUNNING = "running"
    SLEEPING = "sleeping"
    KILLED = "killed"


class RuntimeState(str, Enum):
    """Internal sandbox infrastructure states.

    These are internal orchestration states used by WorkspaceManager and Sandbox
    for lifecycle management. Users never see these directly — they are mapped to
    SessionStatus (running/sleeping/killed) at the public API boundary.
    """

    STARTING = "starting"
    ACTIVE = "active"
    PAUSED = "paused"
    DYING = "dying"
    ENDED = "ended"
    DEAD = "dead"


_RUNTIME_TO_STATUS: dict[RuntimeState, SessionStatus] = {
    RuntimeState.STARTING: SessionStatus.RUNNING,
    RuntimeState.ACTIVE: SessionStatus.RUNNING,
    RuntimeState.PAUSED: SessionStatus.SLEEPING,
    RuntimeState.DYING: SessionStatus.KILLED,
    RuntimeState.ENDED: SessionStatus.KILLED,
    RuntimeState.DEAD: SessionStatus.KILLED,
}


def to_session_status(state: RuntimeState) -> SessionStatus:
    """Map internal RuntimeState to user-facing SessionStatus."""
    return _RUNTIME_TO_STATUS[state]


VALID_RUNTIME_TRANSITIONS: dict[RuntimeState, frozenset[RuntimeState]] = {
    RuntimeState.STARTING: frozenset({RuntimeState.ACTIVE, RuntimeState.DEAD}),
    RuntimeState.ACTIVE: frozenset({RuntimeState.PAUSED, RuntimeState.DYING, RuntimeState.DEAD}),
    RuntimeState.PAUSED: frozenset({RuntimeState.ACTIVE, RuntimeState.DYING, RuntimeState.DEAD}),
    RuntimeState.DYING: frozenset({RuntimeState.ENDED, RuntimeState.DEAD}),
    RuntimeState.ENDED: frozenset(),
    RuntimeState.DEAD: frozenset(),
}


class InvalidTransitionError(Exception):
    """Raised when a state transition is not allowed."""

    def __init__(self, current: RuntimeState | str, target: RuntimeState | str) -> None:
        self.current = current
        self.target = target
        current_val = current.value if isinstance(current, RuntimeState) else current
        target_val = target.value if isinstance(target, RuntimeState) else target
        super().__init__(f"Invalid transition: {current_val!r} → {target_val!r}")


def validate_runtime_transition(current: RuntimeState, target: RuntimeState) -> bool:
    """Return True if the runtime transition from *current* to *target* is allowed."""
    return target in VALID_RUNTIME_TRANSITIONS.get(current, frozenset())
