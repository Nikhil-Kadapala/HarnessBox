"""Durable Project endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from harnessbox._server.workspace_manager import WorkspaceManager

from ._deps import get_manager
from ._models import CreateProjectParams, ProjectResponseParams

router = APIRouter(prefix="/v1/projects", tags=["projects"])


def _project_response(record: dict[str, str]) -> ProjectResponseParams:
    return ProjectResponseParams(**record)


@router.get("", response_model=list[ProjectResponseParams])
async def list_projects(
    mgr: WorkspaceManager = Depends(get_manager),
) -> list[ProjectResponseParams]:
    if mgr.storage is None:
        return []
    return [_project_response(project) for project in await mgr.storage.list_projects()]


@router.post("", response_model=ProjectResponseParams, status_code=201)
async def create_project(
    req: CreateProjectParams,
    mgr: WorkspaceManager = Depends(get_manager),
) -> ProjectResponseParams:
    if mgr.storage is None:
        raise HTTPException(status_code=503, detail="Project storage is unavailable")
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "project_id": str(uuid.uuid4()),
        "name": req.name.strip(),
        "remote": req.remote.strip(),
        "default_branch": req.default_branch.strip(),
        "created_at": now,
        "updated_at": now,
    }
    if not record["name"] or not record["remote"] or not record["default_branch"]:
        raise HTTPException(status_code=422, detail="Name, repository URL, and branch are required")
    try:
        await mgr.storage.save_project(record)
    except KeyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _project_response(record)
