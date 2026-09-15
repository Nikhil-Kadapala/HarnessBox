"""Durable Project endpoints."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from harnessbox._server.workspace_manager import WorkspaceManager

from ._deps import get_manager
from ._models import CreateProjectParams, ProjectResponseParams, UpdateProjectParams

router = APIRouter(prefix="/v1/projects", tags=["projects"])


def _project_response(record: Mapping[str, Any]) -> ProjectResponseParams:
    return ProjectResponseParams.model_validate(record)


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
        "workspace_settings": req.workspace_settings.model_dump(),
    }
    if not record["name"] or not record["remote"] or not record["default_branch"]:
        raise HTTPException(status_code=422, detail="Name, repository URL, and branch are required")
    try:
        await mgr.storage.save_project(record)
    except KeyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _project_response(record)


@router.get("/{project_id}", response_model=ProjectResponseParams)
async def get_project(
    project_id: str, mgr: WorkspaceManager = Depends(get_manager)
) -> ProjectResponseParams:
    if mgr.storage is None:
        raise HTTPException(status_code=503, detail="Project storage is unavailable")
    record = await mgr.storage.get_project(project_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return _project_response(record)


@router.patch("/{project_id}", response_model=ProjectResponseParams)
async def update_project(
    project_id: str,
    req: UpdateProjectParams,
    mgr: WorkspaceManager = Depends(get_manager),
) -> ProjectResponseParams:
    if mgr.storage is None:
        raise HTTPException(status_code=503, detail="Project storage is unavailable")
    current = await mgr.storage.get_project(project_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Project not found")
    changes = req.model_dump(exclude_unset=True, exclude_none=True)
    if "workspace_settings" in changes:
        changes["workspace_settings"] = (
            req.workspace_settings.model_dump() if req.workspace_settings else {}
        )
    if not changes:
        return _project_response(current)
    changes["updated_at"] = datetime.now(timezone.utc).isoformat()
    try:
        await mgr.storage.update_project(project_id, **changes)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    updated = await mgr.storage.get_project(project_id)
    assert updated is not None
    return _project_response(updated)
