"""Workspace lifecycle state machine for sandboxed workspaces.

RuntimeState is the single status vocabulary used by the public SDK, HTTP API,
and internal WorkspaceManager orchestration.
"""

from __future__ import annotations

from enum import Enum


class RuntimeState(str, Enum):
    """Sandbox / workspace lifecycle states.

    Used everywhere — SDK Session.status, HTTP ``state`` field, and internal
    WorkspaceManager transitions.
    """

    STARTING = "starting"
    ACTIVE = "active"
    PAUSED = "paused"
    DYING = "dying"
    ENDED = "ended"
    DEAD = "dead"
    ERROR = "error"


VALID_RUNTIME_TRANSITIONS: dict[RuntimeState, frozenset[RuntimeState]] = {
    RuntimeState.STARTING: frozenset({RuntimeState.ACTIVE, RuntimeState.DEAD, RuntimeState.ERROR}),
    RuntimeState.ACTIVE: frozenset({RuntimeState.PAUSED, RuntimeState.DYING, RuntimeState.DEAD}),
    RuntimeState.PAUSED: frozenset({RuntimeState.ACTIVE, RuntimeState.DYING, RuntimeState.DEAD}),
    RuntimeState.DYING: frozenset({RuntimeState.ENDED, RuntimeState.DEAD}),
    RuntimeState.ENDED: frozenset(),
    RuntimeState.DEAD: frozenset(),
    RuntimeState.ERROR: frozenset({RuntimeState.STARTING}),
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
