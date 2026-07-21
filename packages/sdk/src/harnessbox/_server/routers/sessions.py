"""Workspace endpoints — CRUD, lifecycle, prompting, upload, and event streaming."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import uuid as _uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from sse_starlette.sse import EventSourceResponse, ServerSentEvent

from harnessbox._server.workspace_factory import build_workspace_config
from harnessbox._server.workspace_manager import WorkspaceManager, WorkspaceNotFoundError
from harnessbox.lifecycle import InvalidTransitionError
from harnessbox.streaming import Attachment

from ._deps import get_manager, workspace_response
from ._models import (
    CreateSessionRequest,
    CreateWorkspaceRequestParams,
    CreateWorkspaceResponseParams,
    PermissionRequest,
    PromptRequest,
    UploadFileParams,
)

logger = logging.getLogger("harnessbox.server")

router = APIRouter(tags=["sessions"])

_NON_PROMPTABLE_RUNTIME = frozenset({"dead", "ended", "dying"})


@router.post("/v1/workspaces/create", response_model=CreateWorkspaceResponseParams, status_code=202)
async def create_workspace(
    req: CreateWorkspaceRequestParams | CreateSessionRequest,
    background_tasks: BackgroundTasks,
    mgr: WorkspaceManager = Depends(get_manager),
) -> CreateWorkspaceResponseParams:
    """Create a workspace (slim provision: VM + tools + env + optional git/file_system)."""
    try:
        config = build_workspace_config(req)
        # Server always mints workspace_id — ignore any client-supplied id.
        info = mgr.register_workspace(config)
    except Exception as exc:
        logger.exception("Failed to register workspace")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    async def _provision() -> None:
        await mgr.provision_workspace(info.workspace_id, config)

    background_tasks.add_task(_provision)
    return workspace_response(info)


@router.post("/v1/workspaces", response_model=CreateWorkspaceResponseParams, status_code=202)
async def create_workspace_legacy(
    req: CreateSessionRequest,
    background_tasks: BackgroundTasks,
    mgr: WorkspaceManager = Depends(get_manager),
) -> CreateWorkspaceResponseParams:
    """Deprecated: use POST /v1/workspaces/create."""
    return await create_workspace(req, background_tasks, mgr)


@router.get("/v1/workspaces", response_model=list[CreateWorkspaceResponseParams])
async def list_workspaces(
    mgr: WorkspaceManager = Depends(get_manager),
) -> list[CreateWorkspaceResponseParams]:
    return [workspace_response(s) for s in mgr.list_workspaces()]


@router.get("/v1/workspaces/{workspace_id}", response_model=CreateWorkspaceResponseParams)
async def get_workspace(
    workspace_id: str, mgr: WorkspaceManager = Depends(get_manager)
) -> CreateWorkspaceResponseParams:
    try:
        info = mgr.get_workspace(workspace_id)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Workspace not found") from exc
    return workspace_response(info)


@router.delete("/v1/workspaces/{workspace_id}", status_code=204)
async def destroy_workspace(
    workspace_id: str, mgr: WorkspaceManager = Depends(get_manager)
) -> Response:
    try:
        await mgr.destroy_workspace(workspace_id)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Workspace not found") from exc
    return Response(status_code=204)


@router.post("/v1/workspaces/{workspace_id}/files", status_code=204)
async def upload_workspace_file(
    workspace_id: str,
    req: UploadFileParams,
    mgr: WorkspaceManager = Depends(get_manager),
) -> Response:
    """Upload a file to a path inside the workspace sandbox."""
    try:
        info = mgr.get_workspace(workspace_id)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Workspace not found") from exc

    if info.sandbox_conn is None:
        raise HTTPException(status_code=409, detail="Workspace has no active sandbox")

    if req.content is not None:
        content = req.content
    else:
        assert req.content_b64 is not None
        content = base64.b64decode(req.content_b64).decode("utf-8", errors="replace")

    try:
        await info.sandbox_conn.write_file(req.path, content)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return Response(status_code=204)


@router.get("/v1/workspaces/{workspace_id}/conversations")
async def list_conversations(
    workspace_id: str, mgr: WorkspaceManager = Depends(get_manager)
) -> dict[str, Any]:
    """List conversations for a workspace."""
    try:
        mgr.get_workspace(workspace_id)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Workspace not found") from exc

    if mgr.storage:
        conversations = await mgr.storage.get_conversations(workspace_id=workspace_id)
        return {"conversations": conversations}
    return {"conversations": []}


@router.post("/v1/workspaces/{workspace_id}/pause", response_model=CreateWorkspaceResponseParams)
async def pause_workspace(
    workspace_id: str, mgr: WorkspaceManager = Depends(get_manager)
) -> CreateWorkspaceResponseParams:
    try:
        info = mgr.get_workspace(workspace_id)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Workspace not found") from exc

    try:
        await mgr.pause_workspace(workspace_id)
    except InvalidTransitionError as exc:
        raise HTTPException(
            status_code=409, detail=f"Cannot pause workspace in state: {info.runtime_state}"
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return workspace_response(mgr.get_workspace(workspace_id))


@router.post("/v1/workspaces/{workspace_id}/resume", response_model=CreateWorkspaceResponseParams)
async def resume_workspace(
    workspace_id: str, mgr: WorkspaceManager = Depends(get_manager)
) -> CreateWorkspaceResponseParams:
    try:
        info = mgr.get_workspace(workspace_id)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Workspace not found") from exc

    try:
        await mgr.resume_workspace(workspace_id)
    except InvalidTransitionError as exc:
        raise HTTPException(
            status_code=409, detail=f"Cannot resume workspace in state: {info.runtime_state}"
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return workspace_response(mgr.get_workspace(workspace_id))


@router.post("/v1/workspaces/{workspace_id}/stop", status_code=204)
async def stop_workspace(
    workspace_id: str, mgr: WorkspaceManager = Depends(get_manager)
) -> Response:
    try:
        mgr.get_workspace(workspace_id)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Workspace not found") from exc

    await mgr.stop_workspace(workspace_id)
    return Response(status_code=204)


@router.post(
    "/v1/workspaces/{workspace_id}/retry",
    response_model=CreateWorkspaceResponseParams,
    status_code=202,
)
async def retry_workspace(
    workspace_id: str,
    background_tasks: BackgroundTasks,
    mgr: WorkspaceManager = Depends(get_manager),
) -> CreateWorkspaceResponseParams:
    """Retry provisioning a workspace stuck in ERROR. Transitions ERROR -> STARTING."""
    try:
        info = mgr.get_workspace(workspace_id)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Workspace not found") from exc

    try:
        config = mgr.prepare_retry(workspace_id)
    except InvalidTransitionError as exc:
        raise HTTPException(
            status_code=409, detail=f"Cannot retry workspace in state: {info.runtime_state}"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def _reprovision() -> None:
        await mgr.provision_workspace(workspace_id, config)

    background_tasks.add_task(_reprovision)
    return workspace_response(mgr.get_workspace(workspace_id))


@router.post("/v1/workspaces/{workspace_id}/prompt")
async def prompt_session(
    workspace_id: str, req: PromptRequest, mgr: WorkspaceManager = Depends(get_manager)
) -> EventSourceResponse:
    from harnessbox.config.harness import list_harness_types

    try:
        info = mgr.get_workspace(workspace_id)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc

    available = list_harness_types()
    if req.harness not in available:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown harness: {req.harness!r}. Available: {available}",
        )

    if info.runtime_state in _NON_PROMPTABLE_RUNTIME:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "SESSION_NOT_ACTIVE",
                "runtime_state": info.runtime_state,
                "message": "This session cannot accept prompts in its current state.",
            },
        )

    attachments: list[Attachment] = []
    total_size = 0
    for att in req.attachments:
        raw = base64.b64decode(att.data_b64)
        total_size += len(raw)
        if total_size > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Total attachment size exceeds 10MB")

        att_id = str(_uuid.uuid4())
        size = len(raw)

        if size >= 1024 * 1024:
            att_dir = Path.home() / ".harnessbox" / "attachments" / workspace_id
            att_dir.mkdir(parents=True, exist_ok=True)
            safe_name = Path(att.filename).name or "attachment"
            file_path = att_dir / f"{att_id}_{safe_name}"
            file_path.write_bytes(raw)
            attachments.append(
                Attachment(
                    attachment_id=att_id,
                    filename=att.filename,
                    mime_type=att.mime_type,
                    size_bytes=size,
                    data_b64=None,
                    storage_path=str(file_path),
                )
            )
        else:
            attachments.append(
                Attachment(
                    attachment_id=att_id,
                    filename=att.filename,
                    mime_type=att.mime_type,
                    size_bytes=size,
                    data_b64=att.data_b64,
                )
            )

    async def event_generator() -> Any:
        logger.info("SSE stream started for session %s", workspace_id)
        event_count = 0
        try:
            async for event in mgr.prompt(
                workspace_id,
                req.prompt,
                harness=req.harness,
                conversation_id=req.conversation_id,
                attachments=attachments or None,
            ):
                event_count += 1
                logger.info(
                    "SSE event #%d: %s (kind=%s)",
                    event_count,
                    event.event_type,
                    event.item_kind,
                )
                yield ServerSentEvent(
                    data=json.dumps(event.to_dict()),
                    event="message",
                    id=str(event.sequence),
                )
        except RuntimeError as exc:
            logger.error("Stream error for session %s: %s", workspace_id, exc)
            yield ServerSentEvent(
                data=json.dumps({"event_type": "error", "error_message": str(exc)}),
                event="message",
            )
        logger.info("SSE stream ended for session %s (%d events)", workspace_id, event_count)
        yield ServerSentEvent(data="[DONE]", event="message")

    return EventSourceResponse(event_generator())


@router.get("/v1/workspaces/{workspace_id}/events")
async def stream_events(
    workspace_id: str, request: Request, mgr: WorkspaceManager = Depends(get_manager)
) -> EventSourceResponse:
    """Subscribe to live events from an active or provisioning session (SSE).

    During provisioning (runtime_state=starting), the stream emits runtime.state
    events as the workspace transitions to active or error. Clients can use this
    to wait for creation to complete without polling.
    """
    try:
        info = mgr.get_workspace(workspace_id)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc

    last_event_id_str = request.headers.get("last-event-id")
    last_seq = int(last_event_id_str) if last_event_id_str else None

    async def event_generator() -> Any:
        if info.sandbox_conn is not None:
            if last_seq is not None:
                live_buffer = info.sandbox_conn.event_buffer
                async for event in mgr.event_replay.replay_then_live(
                    workspace_id, last_seq, live_buffer
                ):
                    yield ServerSentEvent(
                        data=json.dumps(event.to_dict()),
                        event="message",
                        id=str(event.sequence),
                    )
            else:
                async for event in info.sandbox_conn.event_buffer.stream(last_seq):
                    yield ServerSentEvent(
                        data=json.dumps(event.to_dict()),
                        event="message",
                        id=str(event.sequence),
                    )
        else:
            # Workspace is provisioning — poll until sandbox appears or terminal state
            terminal = frozenset({"error", "dead", "ended"})
            while True:
                if info.runtime_state in terminal:
                    yield ServerSentEvent(
                        data=json.dumps(
                            {
                                "event_type": "runtime.state",
                                "metadata": {
                                    "runtime_state": info.runtime_state,
                                    "error_message": info.error_message,
                                },
                            }
                        ),
                        event="message",
                    )
                    break
                if info.sandbox_conn is not None:
                    async for event in info.sandbox_conn.event_buffer.stream(last_seq):
                        yield ServerSentEvent(
                            data=json.dumps(event.to_dict()),
                            event="message",
                            id=str(event.sequence),
                        )
                    break
                await asyncio.sleep(0.5)

    return EventSourceResponse(event_generator(), ping=15)


@router.get("/v1/workspaces/{workspace_id}/history")
async def stream_history(
    workspace_id: str,
    after_sequence: int = 0,
    limit: int = 500,
    conversation_id: str | None = None,
    mgr: WorkspaceManager = Depends(get_manager),
) -> EventSourceResponse:
    """Stream historical events from storage via EventReplay."""
    try:
        mgr.get_workspace(workspace_id)
    except WorkspaceNotFoundError:
        if not mgr.storage:
            raise HTTPException(
                status_code=404,
                detail="Session not found and no storage enabled",
            )

    if not mgr.storage:
        raise HTTPException(
            status_code=400,
            detail="Storage not enabled. Historical events not available.",
        )

    async def event_generator() -> Any:
        async for event in mgr.event_replay.get_history(
            workspace_id,
            after_sequence=after_sequence,
            limit=limit,
            conversation_id=conversation_id,
        ):
            yield ServerSentEvent(
                data=json.dumps(event.to_dict()),
                event="message",
                id=str(event.sequence),
            )

    return EventSourceResponse(event_generator(), ping=15)


@router.get("/v1/workspaces/{workspace_id}/events.jsonl")
async def export_events_jsonl(
    workspace_id: str, mgr: WorkspaceManager = Depends(get_manager)
) -> StreamingResponse:
    """Export a workspace's full durable event log as newline-delimited JSON.

    One JSON-encoded event per line (same shape as UniversalEvent.to_dict()),
    ordered by sequence. Unlike /history, this is unpaginated by design — a
    complete export, not a live-reconnect feed.
    """
    try:
        mgr.get_workspace(workspace_id)
    except WorkspaceNotFoundError:
        if not mgr.storage or await mgr.storage.get_workspace(workspace_id) is None:
            raise HTTPException(status_code=404, detail="Session not found")

    if not mgr.storage:
        raise HTTPException(
            status_code=400,
            detail="Storage not enabled. Event export not available.",
        )

    async def body() -> Any:
        async for event in mgr.event_replay.get_history(workspace_id, limit=None):
            yield json.dumps(event.to_dict()).encode() + b"\n"

    return StreamingResponse(
        body(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="{workspace_id}-events.jsonl"'},
    )


@router.post("/v1/workspaces/{workspace_id}/permission")
async def respond_permission(
    workspace_id: str, req: PermissionRequest, mgr: WorkspaceManager = Depends(get_manager)
) -> dict[str, str]:
    try:
        info = mgr.get_workspace(workspace_id)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc
    agent_process = info.sandbox_conn._agent_process
    if not agent_process:
        raise HTTPException(status_code=400, detail="No persistent agent process")
    await agent_process.respond_permission(req.request_id, req.behavior)
    return {"status": "ok"}
