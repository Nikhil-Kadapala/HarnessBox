"""HarnessBox Cloud API — shared SDK routers + auth/billing middleware."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from harnessbox._server.routers import (
    account_router,
    discovery_router,
    sessions_router,
    workspace_router,
)
from harnessbox._server.storage import StorageBackend
from harnessbox._server.workspace_manager import WorkspaceManager

from harnessbox_api.auth import require_auth
from harnessbox_api.config import get_settings
from harnessbox_api.routes.auth_routes import router as auth_router
from harnessbox_api.routes.billing_routes import router as billing_router
from harnessbox_api.routes.teams_routes import router as teams_router

logger = logging.getLogger("harnessbox_api")


def _resolve_storage(storage_name: str, db_path: str) -> StorageBackend:
    from harnessbox._server._storage import get_storage_backend

    backend_cls = get_storage_backend(storage_name)
    kwargs: dict[str, str] = {}
    if storage_name == "sqlite":
        kwargs["path"] = db_path
    storage: StorageBackend = backend_cls(**kwargs)
    return storage


def create_app() -> FastAPI:
    settings = get_settings()

    resolved_storage = _resolve_storage(settings.harnessbox_storage, settings.harnessbox_db_path)
    mgr = WorkspaceManager(storage=resolved_storage)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        if mgr.storage:
            await mgr.storage.initialize()
            await mgr.load_workspaces()
            logger.info("Cloud API storage initialized")
        yield
        await mgr.graceful_shutdown()
        if mgr.storage:
            await mgr.storage.close()

    app = FastAPI(
        title="HarnessBox Cloud API",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.manager = mgr

    # Shared SDK routers — mounted behind auth
    app.include_router(discovery_router, dependencies=[Depends(require_auth)])
    app.include_router(workspace_router, dependencies=[Depends(require_auth)])
    app.include_router(account_router, dependencies=[Depends(require_auth)])
    app.include_router(sessions_router, dependencies=[Depends(require_auth)])

    # Cloud-only routes (auth built into each route's dependencies)
    app.include_router(auth_router)
    app.include_router(billing_router)
    app.include_router(teams_router)

    # Health check — no auth required
    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "harnessbox-cloud-api"}

    return app
