"""Session endpoints — CRUD, lifecycle, prompting, and event streaming for workspaces."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import uuid as _uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import Response
from sse_starlette.sse import EventSourceResponse, ServerSentEvent

from harnessbox._server.workspace_factory import build_workspace_config
from harnessbox._server.workspace_manager import WorkspaceManager, WorkspaceNotFoundError
from harnessbox.lifecycle import InvalidTransitionError, RuntimeState
from harnessbox.sandbox import Sandbox
from harnessbox.streaming import Attachment

from ._deps import get_manager, session_response
from ._models import (
    CreateSessionRequest,
    PermissionRequest,
    PromptRequest,
    PRRequest,
    RenameRequest,
    SessionResponse,
    SessionStatsResponse,
    TransitionRequest,
)

logger = logging.getLogger("harnessbox.server")

router = APIRouter(tags=["sessions"])

_NON_PROMPTABLE_RUNTIME = frozenset({"dead", "ended", "dying"})


@router.post("/v1/workspaces", response_model=SessionResponse, status_code=202)
async def create_session(
    req: CreateSessionRequest,
    background_tasks: BackgroundTasks,
    mgr: WorkspaceManager = Depends(get_manager),
) -> SessionResponse:
    try:
        config = build_workspace_config(req)
        info = mgr.register_workspace(config, workspace_id=req.session_id)
    except Exception as exc:
        logger.exception("Failed to register session")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    async def _provision() -> None:
        await mgr.provision_workspace(info.workspace_id, config)

    background_tasks.add_task(_provision)
    return session_response(info)


@router.get("/v1/workspaces", response_model=list[SessionResponse])
async def list_sessions(mgr: WorkspaceManager = Depends(get_manager)) -> list[SessionResponse]:
    return [session_response(s) for s in mgr.list_workspaces()]


@router.get("/v1/workspaces/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str, mgr: WorkspaceManager = Depends(get_manager)
) -> SessionResponse:
    try:
        info = mgr.get_workspace(session_id)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc
    return session_response(info)


@router.delete("/v1/workspaces/{session_id}", status_code=204)
async def destroy_session(
    session_id: str, mgr: WorkspaceManager = Depends(get_manager)
) -> Response:
    try:
        await mgr.destroy_workspace(session_id)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc
    return Response(status_code=204)


@router.get("/v1/workspaces/{session_id}/conversations")
async def list_conversations(
    session_id: str, mgr: WorkspaceManager = Depends(get_manager)
) -> dict[str, Any]:
    """List conversations for a workspace."""
    try:
        mgr.get_workspace(session_id)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc

    if mgr.storage:
        conversations = await mgr.storage.get_conversations(workspace_id=session_id)
        return {"conversations": conversations}
    return {"conversations": []}


@router.post("/v1/workspaces/{session_id}/pause", response_model=SessionResponse)
async def pause_session(
    session_id: str, mgr: WorkspaceManager = Depends(get_manager)
) -> SessionResponse:
    try:
        info = mgr.get_workspace(session_id)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc

    try:
        await mgr.pause_workspace(session_id)
    except InvalidTransitionError as exc:
        raise HTTPException(
            status_code=409, detail=f"Cannot pause session in state: {info.runtime_state}"
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return session_response(mgr.get_workspace(session_id))


@router.post("/v1/workspaces/{session_id}/resume", response_model=SessionResponse)
async def resume_session(
    session_id: str, mgr: WorkspaceManager = Depends(get_manager)
) -> SessionResponse:
    try:
        info = mgr.get_workspace(session_id)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc

    try:
        await mgr.resume_workspace(session_id)
    except InvalidTransitionError as exc:
        raise HTTPException(
            status_code=409, detail=f"Cannot resume session in state: {info.runtime_state}"
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return session_response(mgr.get_workspace(session_id))


@router.post("/v1/workspaces/{session_id}/stop", status_code=204)
async def stop_session(session_id: str, mgr: WorkspaceManager = Depends(get_manager)) -> Response:
    try:
        info = mgr.get_workspace(session_id)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc

    await info.sandbox_conn.kill()
    info.runtime_state = RuntimeState.DEAD.value
    return Response(status_code=204)


@router.post("/v1/workspaces/{session_id}/rename", response_model=SessionResponse)
async def rename_session(
    session_id: str, req: RenameRequest, mgr: WorkspaceManager = Depends(get_manager)
) -> SessionResponse:
    try:
        info = mgr.get_workspace(session_id)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc

    if info.sandbox_conn and isinstance(info.sandbox_conn, Sandbox):
        try:
            await info.sandbox_conn.rename_branch(req.name)
        except RuntimeError:
            pass
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    info.branch = req.name
    info.workspace_name = req.name
    return session_response(info)


@router.post("/v1/workspaces/{session_id}/pr", response_model=SessionResponse)
async def create_pr(
    session_id: str, req: PRRequest, mgr: WorkspaceManager = Depends(get_manager)
) -> SessionResponse:
    try:
        info = mgr.get_workspace(session_id)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc

    if not info.sandbox_conn or not isinstance(info.sandbox_conn, Sandbox):
        raise HTTPException(status_code=400, detail="Session has no active sandbox")

    try:
        result = await info.sandbox_conn.create_pr(req.title, req.body)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    info.pr_url = result.get("url")
    try:
        mgr.transition_workflow(session_id, "in_review")
    except Exception:
        pass

    return session_response(info)


@router.post("/v1/workspaces/{session_id}/pr/refresh", response_model=SessionResponse)
async def refresh_pr_status(
    session_id: str, mgr: WorkspaceManager = Depends(get_manager)
) -> SessionResponse:
    try:
        info = mgr.get_workspace(session_id)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc

    if not isinstance(info.sandbox_conn, Sandbox) or not info.pr_url:
        return session_response(info)

    try:
        pr_data = await info.sandbox_conn.check_pr_status()
    except RuntimeError:
        return session_response(info)
    except Exception:
        logger.debug("Failed to check PR status for session %s", session_id, exc_info=True)
        return session_response(info)

    if pr_data:
        info.ci_status = pr_data.get("ci_status")
        info.pr_number = pr_data.get("number")
        if pr_data.get("merged"):
            try:
                mgr.transition_workflow(session_id, "merged")
            except Exception:
                pass

    return session_response(info)


@router.post("/v1/workspaces/{session_id}/transition", response_model=SessionResponse)
async def transition_session(
    session_id: str, req: TransitionRequest, mgr: WorkspaceManager = Depends(get_manager)
) -> SessionResponse:
    try:
        info = mgr.get_workspace(session_id)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc

    try:
        if req.dimension == "runtime":
            RuntimeState(req.target_state)
            info = mgr.transition_runtime(session_id, req.target_state)
        elif req.dimension == "workflow":
            info = mgr.transition_workflow(session_id, req.target_state)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown dimension: {req.dimension}. Use 'runtime' or 'workflow'.",
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown state: {req.target_state}") from exc
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return session_response(info)


@router.get("/v1/workspaces/{session_id}/stats", response_model=SessionStatsResponse)
async def get_session_stats(
    session_id: str, mgr: WorkspaceManager = Depends(get_manager)
) -> SessionStatsResponse:
    try:
        info = mgr.get_workspace(session_id)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc

    if not isinstance(info.sandbox_conn, Sandbox):
        return SessionStatsResponse()

    try:
        diff = await info.sandbox_conn.diff_stat()
        commits = await info.sandbox_conn.commit_count()
    except RuntimeError:
        return SessionStatsResponse()
    except Exception:
        logger.debug("Failed to fetch stats for session %s", session_id, exc_info=True)
        return SessionStatsResponse()

    return SessionStatsResponse(
        insertions=diff["insertions"],
        deletions=diff["deletions"],
        commit_count=commits,
    )


@router.post("/v1/workspaces/{session_id}/prompt")
async def prompt_session(
    session_id: str, req: PromptRequest, mgr: WorkspaceManager = Depends(get_manager)
) -> EventSourceResponse:
    from harnessbox.config.harness import list_harness_types

    try:
        info = mgr.get_workspace(session_id)
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
            att_dir = Path.home() / ".harnessbox" / "attachments" / session_id
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
        logger.info("SSE stream started for session %s", session_id)
        event_count = 0
        try:
            async for event in mgr.prompt(
                session_id,
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
            logger.error("Stream error for session %s: %s", session_id, exc)
            yield ServerSentEvent(
                data=json.dumps({"event_type": "error", "error_message": str(exc)}),
                event="message",
            )
        logger.info("SSE stream ended for session %s (%d events)", session_id, event_count)
        yield ServerSentEvent(data="[DONE]", event="message")

    return EventSourceResponse(event_generator())


@router.get("/v1/workspaces/{session_id}/events")
async def stream_events(
    session_id: str, request: Request, mgr: WorkspaceManager = Depends(get_manager)
) -> EventSourceResponse:
    """Subscribe to live events from an active or provisioning session (SSE).

    During provisioning (runtime_state=starting), the stream emits runtime.state
    events as the workspace transitions to active or error. Clients can use this
    to wait for creation to complete without polling.
    """
    try:
        info = mgr.get_workspace(session_id)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc

    last_event_id_str = request.headers.get("last-event-id")
    last_seq = int(last_event_id_str) if last_event_id_str else None

    async def event_generator() -> Any:
        if info.sandbox_conn is not None:
            if last_seq is not None:
                live_buffer = info.sandbox_conn.event_buffer
                async for event in mgr.event_replay.replay_then_live(
                    session_id, last_seq, live_buffer
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
                        data=json.dumps({
                            "event_type": "runtime.state",
                            "metadata": {
                                "runtime_state": info.runtime_state,
                                "error_message": info.error_message,
                            },
                        }),
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


@router.get("/v1/workspaces/{session_id}/history")
async def stream_history(
    session_id: str,
    after_sequence: int = 0,
    limit: int = 500,
    conversation_id: str | None = None,
    mgr: WorkspaceManager = Depends(get_manager),
) -> EventSourceResponse:
    """Stream historical events from storage via EventReplay."""
    try:
        mgr.get_workspace(session_id)
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
            session_id,
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


@router.post("/v1/workspaces/{session_id}/permission")
async def respond_permission(
    session_id: str, req: PermissionRequest, mgr: WorkspaceManager = Depends(get_manager)
) -> dict[str, str]:
    try:
        info = mgr.get_workspace(session_id)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc
    agent_process = info.sandbox_conn._agent_process
    if not agent_process:
        raise HTTPException(status_code=400, detail="No persistent agent process")
    await agent_process.respond_permission(req.request_id, req.behavior)
    return {"status": "ok"}
