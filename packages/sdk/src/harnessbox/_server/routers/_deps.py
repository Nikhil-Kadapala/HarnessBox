"""FastAPI dependencies shared across routers."""

from __future__ import annotations

from typing import Any

from fastapi import Request

from harnessbox._server.workspace_manager import WorkspaceManager

from ._models import SessionResponse


def get_manager(request: Request) -> WorkspaceManager:
    """Retrieve the WorkspaceManager from app state."""
    mgr: WorkspaceManager = request.app.state.manager
    return mgr


def session_response(info: Any) -> SessionResponse:
    """Convert a WorkspaceInstance to a SessionResponse."""
    return SessionResponse(
        session_id=info.workspace_id,
        harness=info.harness,
        runtime_state=info.runtime_state,
        workflow_state=info.workflow_state,
        created_at=info.created_at,
        workspace_name=info.workspace_name,
        branch=info.branch,
        base_branch=info.base_branch,
        remote=info.remote,
        pr_url=info.pr_url,
        pr_number=info.pr_number,
        ci_status=info.ci_status,
        total_cost_usd=info.total_cost_usd,
        error_message=info.error_message,
    )
