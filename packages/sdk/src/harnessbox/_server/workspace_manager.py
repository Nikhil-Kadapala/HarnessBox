"""Workspace management facade — composes registry, idle, session router, and event replay."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

from harnessbox._server.event_replay import EventReplay
from harnessbox._server.idle import IdleOrchestrator
from harnessbox._server.registry import (
    WorkspaceConfig,
    WorkspaceInstance,
    WorkspaceNotFoundError,
    WorkspaceRegistry,
)
from harnessbox._server.session_router import SessionRouter
from harnessbox.streaming import Attachment, UniversalEvent

if TYPE_CHECKING:
    from harnessbox._server.storage import StorageBackend

logger = logging.getLogger(__name__)

__all__ = [
    "WorkspaceConfig",
    "WorkspaceInstance",
    "WorkspaceManager",
    "WorkspaceNotFoundError",
]


class WorkspaceManager:
    """Facade composing WorkspaceRegistry, IdleOrchestrator, SessionRouter, and EventReplay."""

    def __init__(
        self,
        storage: StorageBackend | None = None,
        *,
        auto_pause: bool = True,
        pause_timeout: int = 1800,
    ) -> None:
        self._registry = WorkspaceRegistry(storage)
        self._idle = IdleOrchestrator(
            pause_timeout=pause_timeout,
            auto_pause=auto_pause,
            pause_callback=self._auto_pause_workspace,
        )
        self._router = SessionRouter(self._registry, self._idle, storage)
        self._event_replay = EventReplay(storage)

    @property
    def registry(self) -> WorkspaceRegistry:
        return self._registry

    @property
    def idle(self) -> IdleOrchestrator:
        return self._idle

    @property
    def storage(self) -> StorageBackend | None:
        return self._registry._storage

    @property
    def event_replay(self) -> EventReplay:
        return self._event_replay

    @classmethod
    async def create(
        cls,
        storage: StorageBackend | None = None,
        **kwargs: Any,
    ) -> WorkspaceManager:
        """Async factory with optional persistence."""
        mgr = cls(storage, **kwargs)
        await mgr._registry.initialize()
        return mgr

    def register_workspace(
        self,
        config: WorkspaceConfig,
        *,
        workspace_id: str | None = None,
    ) -> WorkspaceInstance:
        """Register a workspace in STARTING state (no sandbox yet). Returns immediately."""
        return self._registry.register_workspace(config, workspace_id=workspace_id)

    async def provision_workspace(
        self,
        workspace_id: str,
        config: WorkspaceConfig,
        *,
        event_handler: Any = None,
    ) -> WorkspaceInstance:
        """Provision the sandbox for a registered workspace. Starts idle timer on success."""
        info = await self._registry.provision_workspace(
            workspace_id, config, event_handler=event_handler
        )
        if info.runtime_state == "active":
            self._idle.start_timer(info.workspace_id)
        return info

    async def create_workspace(
        self,
        config: WorkspaceConfig,
        *,
        workspace_id: str | None = None,
        event_handler: Any = None,
    ) -> WorkspaceInstance:
        """Create a new workspace with live sandbox (synchronous convenience)."""
        info = await self._registry.create_workspace(
            config, workspace_id=workspace_id, event_handler=event_handler
        )
        if info.runtime_state == "active":
            self._idle.start_timer(info.workspace_id)
        return info

    def get_workspace(self, workspace_id: str) -> WorkspaceInstance:
        """Return workspace by ID or raise WorkspaceNotFoundError."""
        return self._registry.get_workspace(workspace_id)

    def list_workspaces(self) -> list[WorkspaceInstance]:
        """List all workspaces currently in memory."""
        return self._registry.list_workspaces()

    async def load_workspaces(self, limit: int = 100) -> None:
        """Load recent workspaces from storage into memory."""
        await self._registry.load_workspaces(limit=limit)

    def find_by_repo_branch(self, remote: str, branch: str) -> WorkspaceInstance | None:
        """Find a workspace matching a repo remote URL and branch name."""
        return self._registry.find_by_repo_branch(remote, branch)

    async def get_or_create_workspace(
        self,
        remote: str,
        branch: str,
        *,
        config: WorkspaceConfig | None = None,
        workspace_id: str | None = None,
    ) -> WorkspaceInstance:
        """Get existing paused workspace or create new one."""
        info = await self._registry.get_or_create_workspace(
            remote, branch, config=config, workspace_id=workspace_id
        )
        self._idle.start_timer(info.workspace_id)
        return info

    async def prompt(
        self,
        workspace_id: str,
        prompt: str,
        *,
        harness: str = "claude-code",
        conversation_id: str | None = None,
        attachments: list[Attachment] | None = None,
    ) -> AsyncGenerator[UniversalEvent, None]:
        """Send prompt to workspace, streaming events back."""
        async for event in self._router.prompt(
            workspace_id,
            prompt,
            harness=harness,
            conversation_id=conversation_id,
            attachments=attachments,
        ):
            yield event

    def prepare_retry(self, workspace_id: str) -> WorkspaceConfig:
        """Validate ERROR->STARTING and transition; returns config for reprovisioning."""
        return self._registry.prepare_retry(workspace_id)

    async def pause_workspace(self, workspace_id: str) -> None:
        """Pause workspace: snapshot, suspend sandbox, persist."""
        self._idle.cancel_timer(workspace_id)
        await self._registry.pause_workspace(workspace_id)

    async def resume_workspace(self, workspace_id: str) -> None:
        """Resume paused workspace."""
        await self._registry.resume_workspace(workspace_id)
        self._idle.start_timer(workspace_id)

    async def destroy_workspace(self, workspace_id: str) -> None:
        """Destroy a workspace and kill its sandbox."""
        self._idle.remove_workspace(workspace_id)
        await self._registry.destroy_workspace(workspace_id)

    async def stop_workspace(self, workspace_id: str) -> None:
        """Kill a workspace's sandbox, leaving its record queryable as DEAD."""
        self._idle.remove_workspace(workspace_id)
        await self._registry.stop_workspace(workspace_id)

    async def graceful_shutdown(self) -> None:
        """Pause all active workspaces with snapshots for later recovery."""
        self._idle.cancel_all()
        await self._registry.graceful_shutdown()

    async def shutdown_all(self) -> None:
        """Destroy all active workspaces."""
        self._idle.cancel_all()
        await self._registry.shutdown_all()

    async def _auto_pause_workspace(self, workspace_id: str) -> None:
        """Callback for IdleOrchestrator when timeout fires."""
        info = self._registry.get_workspace(workspace_id)
        if info.runtime_state == "active" and info.sandbox_conn is not None:
            await self._registry.pause_workspace(workspace_id)
