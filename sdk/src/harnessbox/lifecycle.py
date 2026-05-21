"""Workspace lifecycle state machine for sandboxed workspaces.

Two independent state dimensions:
- RuntimeState: sandbox infrastructure (is the VM running?)
- WorkflowState: project/PR lifecycle (what stage is the branch work in?)

These are independent. ARCHIVED is terminal for WorkflowState and takes precedence
(once archived, the workspace is done regardless of runtime state).
"""

from __future__ import annotations

from enum import Enum


class RuntimeState(str, Enum):
    """Sandbox infrastructure states — managed by WorkspaceManager/Sandbox."""

    STARTING = "starting"
    ACTIVE = "active"
    PAUSED = "paused"
    ENDING = "ending"
    ENDED = "ended"
    FAILED = "failed"


class WorkflowState(str, Enum):
    """Project/PR lifecycle states — managed by the app/server layer."""

    BACKLOG = "backlog"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    MERGED = "merged"
    ARCHIVED = "archived"


VALID_RUNTIME_TRANSITIONS: dict[RuntimeState, frozenset[RuntimeState]] = {
    RuntimeState.STARTING: frozenset({RuntimeState.ACTIVE, RuntimeState.FAILED}),
    RuntimeState.ACTIVE: frozenset(
        {RuntimeState.PAUSED, RuntimeState.ENDING, RuntimeState.FAILED}
    ),
    RuntimeState.PAUSED: frozenset({RuntimeState.ACTIVE, RuntimeState.ENDING, RuntimeState.FAILED}),
    RuntimeState.ENDING: frozenset({RuntimeState.ENDED, RuntimeState.FAILED}),
    RuntimeState.ENDED: frozenset(),
    RuntimeState.FAILED: frozenset(),
}

VALID_WORKFLOW_TRANSITIONS: dict[WorkflowState, frozenset[WorkflowState]] = {
    WorkflowState.BACKLOG: frozenset({WorkflowState.IN_PROGRESS, WorkflowState.ARCHIVED}),
    WorkflowState.IN_PROGRESS: frozenset(
        {WorkflowState.IN_REVIEW, WorkflowState.ARCHIVED}
    ),
    WorkflowState.IN_REVIEW: frozenset(
        {WorkflowState.IN_PROGRESS, WorkflowState.MERGED, WorkflowState.ARCHIVED}
    ),
    WorkflowState.MERGED: frozenset({WorkflowState.ARCHIVED}),
    WorkflowState.ARCHIVED: frozenset(),
}


class InvalidTransitionError(Exception):
    """Raised when a state transition is not allowed."""

    def __init__(self, current: RuntimeState | WorkflowState, target: RuntimeState | WorkflowState) -> None:
        self.current = current
        self.target = target
        super().__init__(f"Invalid transition: {current.value!r} → {target.value!r}")


def validate_runtime_transition(current: RuntimeState, target: RuntimeState) -> bool:
    """Return True if the runtime transition from *current* to *target* is allowed."""
    return target in VALID_RUNTIME_TRANSITIONS.get(current, frozenset())


def validate_workflow_transition(current: WorkflowState, target: WorkflowState) -> bool:
    """Return True if the workflow transition from *current* to *target* is allowed."""
    return target in VALID_WORKFLOW_TRANSITIONS.get(current, frozenset())


# ---------------------------------------------------------------------------
# Backward compatibility — deprecated aliases
# ---------------------------------------------------------------------------

WorkspaceState = RuntimeState
"""Deprecated: Use RuntimeState for sandbox states or WorkflowState for PR states."""

VALID_TRANSITIONS = VALID_RUNTIME_TRANSITIONS
"""Deprecated: Use VALID_RUNTIME_TRANSITIONS or VALID_WORKFLOW_TRANSITIONS."""


def validate_transition(current: RuntimeState, target: RuntimeState) -> bool:
    """Deprecated: Use validate_runtime_transition()."""
    return validate_runtime_transition(current, target)
