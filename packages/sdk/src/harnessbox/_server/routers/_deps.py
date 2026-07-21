"""FastAPI dependencies shared across routers."""

from __future__ import annotations

from typing import Any

from fastapi import Request

from harnessbox._server.workspace_manager import WorkspaceManager

from ._models import CreateWorkspaceResponseParams


def get_manager(request: Request) -> WorkspaceManager:
    """Retrieve the WorkspaceManager from app state."""
    mgr: WorkspaceManager = request.app.state.manager
    return mgr


def workspace_response(info: Any) -> CreateWorkspaceResponseParams:
    """Convert a WorkspaceInstance to a CreateWorkspaceResponseParams."""
    return CreateWorkspaceResponseParams(
        workspace_id=info.workspace_id,
        state=info.runtime_state,
        created_at=info.created_at,
        harness=info.harness,
        project_id=getattr(info, "project_id", None),
        workspace_name=info.workspace_name,
        branch=info.branch,
        base_branch=info.base_branch,
        remote=info.remote,
        mount_path=getattr(info, "mount_path", None),
        total_cost_usd=info.total_cost_usd,
        error_message=info.error_message,
    )


# Backwards-compatible alias
session_response = workspace_response
