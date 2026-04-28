"""HTTP/SSE transport layer for HarnessBox sessions.

Exposes session management and agent event streaming over HTTP.
Install with ``pip install harnessbox[server]`` for dependencies.

    uvicorn harnessbox.server:create_app --factory --port 8000

Endpoints:
    POST   /v1/sessions              — create session
    GET    /v1/sessions              — list sessions
    GET    /v1/sessions/{id}         — get session info
    DELETE /v1/sessions/{id}         — destroy session
    POST   /v1/sessions/{id}/prompt  — send prompt, SSE response
    GET    /v1/sessions/{id}/events  — subscribe to events (SSE)
    POST   /v1/sessions/{id}/permission — respond to permission request
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import Response
    from pydantic import BaseModel
    from sse_starlette.sse import EventSourceResponse
except ImportError as e:
    raise ImportError(
        "Server dependencies not installed. Run: pip install harnessbox[server]"
    ) from e

from harnessbox.session import SessionConfig, SessionManager, SessionNotFoundError

logging.basicConfig(level=logging.DEBUG, format="%(name)s %(levelname)s: %(message)s")
logger = logging.getLogger("harnessbox.server")

_PROVIDER_KEY_NAMES: dict[str, list[str]] = {
    "e2b": ["E2B_API_KEY", "E2B_ACCESS_TOKEN"],
}


def _extract_provider_key(provider: str, env_vars: dict[str, str]) -> str | None:
    for key_name in _PROVIDER_KEY_NAMES.get(provider, []):
        if key_name in env_vars:
            return env_vars[key_name]
    return None


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class CreateSessionRequest(BaseModel):
    provider: str = "e2b"
    api_key: str | None = None
    harness: str = "claude-code"
    env_vars: dict[str, str] = {}
    setup_script: str | None = None
    cwd: str | None = None
    timeout: int = 900
    skip_permissions: bool = False
    template: str | None = None
    session_id: str | None = None


class SessionResponse(BaseModel):
    session_id: str
    harness: str
    status: str
    created_at: str


class PromptRequest(BaseModel):
    prompt: str


class PermissionRequest(BaseModel):
    request_id: str
    behavior: str = "allow"


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(*, manager: SessionManager | None = None) -> FastAPI:
    """Create a FastAPI app wired to the given SessionManager."""
    mgr = manager or SessionManager()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        yield
        await mgr.shutdown_all()

    app = FastAPI(
        title="HarnessBox",
        version="0.2.0",
        lifespan=lifespan,
    )

    @app.post("/v1/sessions", response_model=SessionResponse, status_code=201)
    async def create_session(req: CreateSessionRequest) -> SessionResponse:
        env_vars = req.env_vars
        api_key = req.api_key or _extract_provider_key(req.provider, env_vars)
        config = SessionConfig(
            provider=req.provider,
            api_key=api_key,
            harness=req.harness,
            env_vars=env_vars,
            setup_script=req.setup_script,
            cwd=req.cwd,
            timeout=req.timeout,
            skip_permissions=req.skip_permissions,
            template=req.template,
        )
        try:
            info = await mgr.create_session(config, session_id=req.session_id)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return SessionResponse(
            session_id=info.session_id,
            harness=info.harness,
            status=info.status,
            created_at=info.created_at,
        )

    @app.get("/v1/sessions", response_model=list[SessionResponse])
    async def list_sessions() -> list[SessionResponse]:
        return [
            SessionResponse(
                session_id=s.session_id,
                harness=s.harness,
                status=s.status,
                created_at=s.created_at,
            )
            for s in mgr.list_sessions()
        ]

    @app.get("/v1/sessions/{session_id}", response_model=SessionResponse)
    async def get_session(session_id: str) -> SessionResponse:
        try:
            info = mgr.get_session(session_id)
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        return SessionResponse(
            session_id=info.session_id,
            harness=info.harness,
            status=info.status,
            created_at=info.created_at,
        )

    @app.delete("/v1/sessions/{session_id}", status_code=204)
    async def destroy_session(session_id: str) -> Response:
        try:
            await mgr.destroy_session(session_id)
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        return Response(status_code=204)

    @app.post("/v1/sessions/{session_id}/prompt")
    async def prompt_session(session_id: str, req: PromptRequest) -> EventSourceResponse:
        try:
            mgr.get_session(session_id)
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc

        async def event_generator() -> Any:
            logger.info("SSE stream started for session %s", session_id)
            event_count = 0
            try:
                async for event in mgr.prompt(session_id, req.prompt):
                    event_count += 1
                    logger.info(
                        "SSE event #%d: %s (kind=%s)",
                        event_count,
                        event.event_type,
                        event.item_kind,
                    )
                    yield {
                        "event": "message",
                        "id": str(event.sequence),
                        "data": json.dumps(event.to_dict()),
                    }
            except RuntimeError as exc:
                logger.error("Stream error for session %s: %s", session_id, exc)
                yield {
                    "event": "message",
                    "data": json.dumps({"event_type": "error", "error_message": str(exc)}),
                }
            logger.info("SSE stream ended for session %s (%d events)", session_id, event_count)
            yield {"event": "message", "data": "[DONE]"}

        return EventSourceResponse(event_generator())

    @app.get("/v1/sessions/{session_id}/events")
    async def stream_events(session_id: str, request: Request) -> EventSourceResponse:
        try:
            info = mgr.get_session(session_id)
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc

        last_event_id_str = request.headers.get("last-event-id")
        last_seq = int(last_event_id_str) if last_event_id_str else None

        async def event_generator() -> Any:
            async for event in info.sandbox.event_buffer.stream(last_seq):
                yield {
                    "event": "message",
                    "id": str(event.sequence),
                    "data": json.dumps(event.to_dict()),
                }

        return EventSourceResponse(event_generator(), ping=15)

    @app.post("/v1/sessions/{session_id}/permission")
    async def respond_permission(session_id: str, req: PermissionRequest) -> dict[str, str]:
        try:
            info = mgr.get_session(session_id)
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        agent_process = info.sandbox._agent_process
        if not agent_process:
            raise HTTPException(status_code=400, detail="No persistent agent process")
        await agent_process.respond_permission(req.request_id, req.behavior)
        return {"status": "ok"}

    return app
