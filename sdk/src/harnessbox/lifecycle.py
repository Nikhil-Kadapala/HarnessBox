"""Workspace lifecycle state machine for sandboxed workspaces."""

from __future__ import annotations

from enum import Enum


class WorkspaceState(str, Enum):
    BACKLOG = "backlog"
    STARTING = "starting"
    ACTIVE = "active"
    PAUSED = "paused"
    IN_REVIEW = "in_review"
    ENDING = "ending"
    MERGED = "merged"
    FAILED = "failed"
    ARCHIVED = "archived"


VALID_TRANSITIONS: dict[WorkspaceState, frozenset[WorkspaceState]] = {
    WorkspaceState.BACKLOG: frozenset({WorkspaceState.STARTING, WorkspaceState.ARCHIVED}),
    WorkspaceState.STARTING: frozenset({WorkspaceState.ACTIVE, WorkspaceState.FAILED}),
    WorkspaceState.ACTIVE: frozenset(
        {WorkspaceState.PAUSED, WorkspaceState.ENDING, WorkspaceState.IN_REVIEW, WorkspaceState.FAILED}
    ),
    WorkspaceState.PAUSED: frozenset({WorkspaceState.ACTIVE, WorkspaceState.ENDING, WorkspaceState.FAILED}),
    WorkspaceState.IN_REVIEW: frozenset(
        {WorkspaceState.ACTIVE, WorkspaceState.ENDING, WorkspaceState.MERGED, WorkspaceState.ARCHIVED}
    ),
    WorkspaceState.ENDING: frozenset({WorkspaceState.MERGED, WorkspaceState.FAILED}),
    WorkspaceState.MERGED: frozenset({WorkspaceState.ARCHIVED}),
    WorkspaceState.FAILED: frozenset({WorkspaceState.ARCHIVED}),
    WorkspaceState.ARCHIVED: frozenset(),
}


class InvalidTransitionError(Exception):
    """Raised when a state transition is not allowed."""

    def __init__(self, current: WorkspaceState, target: WorkspaceState) -> None:
        self.current = current
        self.target = target
        super().__init__(f"Invalid transition: {current.value!r} → {target.value!r}")


def validate_transition(current: WorkspaceState, target: WorkspaceState) -> bool:
    """Return True if the transition from *current* to *target* is allowed."""
    return target in VALID_TRANSITIONS.get(current, frozenset())
