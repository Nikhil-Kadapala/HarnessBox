"""HTTP/SSE transport layer for HarnessBox workspaces.

Exposes workspace management and agent event streaming over HTTP.
Install with ``pip install harnessbox[server]`` for dependencies.

    uvicorn harnessbox.server:create_app --factory --port 8000

Endpoints:
    GET    /v1/workspace/name              — generate workspace name
    GET    /v1/workspace/detect            — detect repo from path
    POST   /v1/workspaces/create           — create workspace (slim provision)
    POST   /v1/workspaces                  — deprecated alias for create
    GET    /v1/workspaces                  — list workspaces
    GET    /v1/workspaces/{id}             — get workspace info
    DELETE /v1/workspaces/{id}             — destroy workspace
    POST   /v1/workspaces/{id}/files       — upload a file into the sandbox
    GET    /v1/workspaces/{id}/conversations — list conversations
    POST   /v1/workspaces/{id}/prompt      — send prompt, SSE response
    GET    /v1/workspaces/{id}/events      — subscribe to live events (SSE)
    GET    /v1/workspaces/{id}/history     — stream historical events from storage
    POST   /v1/workspaces/{id}/permission  — respond to permission request
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

try:
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
except ImportError as e:
    raise ImportError(
        "Server dependencies not installed. Run: pip install harnessbox[server]"
    ) from e

from harnessbox._server.routers import (
    account_router,
    discovery_router,
    sessions_router,
    workspace_router,
)

# Backward-compat re-exports (used in tests, workspace_factory)
from harnessbox._server.routers._models import (  # noqa: F401
    AttachmentPayload,
    CreateSessionRequest,
    CreateWorkspaceRequestParams,
    CreateWorkspaceResponseParams,
    GitCredentialsParams,
    GitSourceParams,
    MountSourceParams,
    PermissionRequest,
    PromptRequest,
    SecurityPolicyRequest,
    SessionResponse,
    UploadFileParams,
    WorkspaceRequest,
)
from harnessbox._server.storage import StorageBackend
from harnessbox._server.workspace_manager import WorkspaceManager

logging.basicConfig(level=logging.DEBUG, format="%(name)s %(levelname)s: %(message)s")
logger = logging.getLogger("harnessbox.server")


def create_app(
    *,
    manager: WorkspaceManager | None = None,
    storage: str | StorageBackend | None = "sqlite",
) -> FastAPI:
    """Create a FastAPI app with persistent storage (SQLite by default).

    Args:
        manager: Existing WorkspaceManager instance (or None to create).
        storage: Storage backend name ("memory", "sqlite"), instance, or None.
                 Defaults to "sqlite" for persistent sessions across restarts.
                 Pass None for pure in-memory (tests only).

    Returns:
        FastAPI app ready to run with uvicorn.
    """
    import os as _os

    if storage == "sqlite":
        env_storage = _os.environ.get("HARNESSBOX_STORAGE", "sqlite")
        if env_storage != "sqlite":
            storage = env_storage

    resolved_storage: StorageBackend | None = None
    if isinstance(storage, str):
        from harnessbox._server._storage import get_storage_backend

        backend_cls = get_storage_backend(storage)
        kwargs: dict[str, Any] = {}
        if storage == "sqlite":
            db_path = _os.environ.get("HARNESSBOX_DB_PATH")
            if db_path:
                kwargs["path"] = db_path
        resolved_storage = backend_cls(**kwargs)
    elif storage is not None:
        resolved_storage = storage

    if manager is not None:
        mgr = manager
    else:
        mgr = WorkspaceManager(storage=resolved_storage)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        if mgr.storage:
            await mgr.storage.initialize()
            await mgr.load_workspaces()
            logger.info("Storage initialized and workspaces loaded")

        yield

        await mgr.graceful_shutdown()

        if mgr.storage:
            await mgr.storage.close()
            logger.info("Storage closed")

    app = FastAPI(
        title="HarnessBox",
        version="0.2.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.manager = mgr

    app.include_router(discovery_router)
    app.include_router(workspace_router)
    app.include_router(account_router)
    app.include_router(sessions_router)

    return app
