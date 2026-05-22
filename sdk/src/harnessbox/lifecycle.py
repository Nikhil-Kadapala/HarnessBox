"""Workspace lifecycle state machine for sandboxed workspaces.

Two independent state dimensions:
- RuntimeState: sandbox infrastructure (is the VM running?)
- WorkflowState: project/PR lifecycle (what stage is the branch work in?)

These are independent. ARCHIVED is terminal for WorkflowState and takes precedence
(once archived, the workspace is done regardless of runtime state).
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


class WorkflowState(str, Enum):
    """Project/PR lifecycle states — managed by the app/server layer."""

    BACKLOG = "backlog"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    MERGED = "merged"
    ARCHIVED = "archived"


VALID_RUNTIME_TRANSITIONS: dict[RuntimeState, frozenset[RuntimeState]] = {
    RuntimeState.STARTING: frozenset({RuntimeState.ACTIVE, RuntimeState.DEAD}),
    RuntimeState.ACTIVE: frozenset({RuntimeState.PAUSED, RuntimeState.DYING, RuntimeState.DEAD}),
    RuntimeState.PAUSED: frozenset({RuntimeState.ACTIVE, RuntimeState.DYING, RuntimeState.DEAD}),
    RuntimeState.DYING: frozenset({RuntimeState.ENDED, RuntimeState.DEAD}),
    RuntimeState.ENDED: frozenset(),
    RuntimeState.DEAD: frozenset(),
}

VALID_WORKFLOW_TRANSITIONS: dict[WorkflowState, frozenset[WorkflowState]] = {
    WorkflowState.BACKLOG: frozenset({WorkflowState.IN_PROGRESS, WorkflowState.ARCHIVED}),
    WorkflowState.IN_PROGRESS: frozenset({WorkflowState.IN_REVIEW, WorkflowState.ARCHIVED}),
    WorkflowState.IN_REVIEW: frozenset(
        {WorkflowState.IN_PROGRESS, WorkflowState.MERGED, WorkflowState.ARCHIVED}
    ),
    WorkflowState.MERGED: frozenset({WorkflowState.ARCHIVED}),
    WorkflowState.ARCHIVED: frozenset(),
}


class InvalidTransitionError(Exception):
    """Raised when a state transition is not allowed."""

    def __init__(
        self, current: RuntimeState | WorkflowState, target: RuntimeState | WorkflowState
    ) -> None:
        self.current = current
        self.target = target
        super().__init__(f"Invalid transition: {current.value!r} → {target.value!r}")


def validate_runtime_transition(current: RuntimeState, target: RuntimeState) -> bool:
    """Return True if the runtime transition from *current* to *target* is allowed."""
    return target in VALID_RUNTIME_TRANSITIONS.get(current, frozenset())


def validate_workflow_transition(current: WorkflowState, target: WorkflowState) -> bool:
    """Return True if the workflow transition from *current* to *target* is allowed."""
    return target in VALID_WORKFLOW_TRANSITIONS.get(current, frozenset())


