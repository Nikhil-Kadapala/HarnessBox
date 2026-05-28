"""Workspace management facade — composes registry, idle, session router, and event replay.

Preserves the existing public API (WorkspaceManager, WorkspaceConfig, WorkspaceInstance,
WorkspaceNotFoundError) for backward compatibility. Internally delegates to focused modules.
"""

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
    """Facade composing WorkspaceRegistry, IdleOrchestrator, SessionRouter, and EventReplay.

    Preserves the same public API as the original monolithic WorkspaceManager.
    """

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

    async def create_workspace(
        self,
        config: WorkspaceConfig,
        *,
        workspace_id: str | None = None,
        event_handler: Any = None,
    ) -> WorkspaceInstance:
        """Create a new workspace with live sandbox."""
        info = await self._registry.create_workspace(
            config, workspace_id=workspace_id, event_handler=event_handler
        )
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

    def transition_runtime(self, workspace_id: str, target_state: str) -> WorkspaceInstance:
        """Transition workspace runtime state with validation."""
        return self._registry.transition_runtime(workspace_id, target_state)

    def transition_workflow(self, workspace_id: str, target_state: str) -> WorkspaceInstance:
        """Transition workspace workflow state with validation."""
        return self._registry.transition_workflow(workspace_id, target_state)

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

    # --- Compatibility properties for tests that access internal state ---

    @property
    def _storage(self) -> Any:
        return self._registry._storage

    @_storage.setter
    def _storage(self, value: Any) -> None:
        self._registry._storage = value
        self._router._storage = value
        self._event_replay._storage = value

    @property
    def _idle_timers(self) -> dict[str, Any]:
        return self._idle._idle_timers

    @property
    def _active_turns(self) -> dict[str, int]:
        return self._idle._active_turns

    @property
    def _auto_pause(self) -> bool:
        return self._idle._auto_pause

    @property
    def _pause_timeout(self) -> int:
        return self._idle._pause_timeout

    @property
    def _workspaces(self) -> dict[str, WorkspaceInstance]:
        return self._registry._workspaces

    @property
    def _locks(self) -> dict[str, Any]:
        return self._registry._locks

    @property
    def _workspace_configs(self) -> dict[str, WorkspaceConfig]:
        return self._registry._workspace_configs

    def _start_idle_timer(self, workspace_id: str) -> None:
        self._idle.start_timer(workspace_id)

    def _cancel_idle_timer(self, workspace_id: str) -> None:
        self._idle.cancel_timer(workspace_id)

    async def _pause_workspace(self, workspace_id: str) -> None:
        self._idle.cancel_timer(workspace_id)
        info = self._registry.get_workspace(workspace_id)
        if not info.sandbox_conn:
            return
        async with self._registry._ensure_lock(workspace_id):
            await self._registry._pause_workspace_locked(workspace_id, info)

    async def _resume_workspace(self, workspace_id: str) -> None:
        info = self._registry.get_workspace(workspace_id)
        if not info.sandbox_conn:
            await self._registry._connect_sandbox(workspace_id)
            self._idle.start_timer(workspace_id)
            return
        async with self._registry._ensure_lock(workspace_id):
            if info.runtime_state != "paused":
                return
            await self._registry._resume_workspace_locked(workspace_id, info)
        self._idle.start_timer(workspace_id)

    async def _connect_sandbox(self, workspace_id: str) -> None:
        await self._registry._connect_sandbox(workspace_id)
        self._idle.start_timer(workspace_id)

    async def _ensure_sandbox(self, workspace_id: str) -> None:
        await self._registry.ensure_sandbox(workspace_id)

    async def _idle_countdown(self, workspace_id: str) -> None:
        info = self._registry._workspaces.get(workspace_id)
        if info and info.runtime_state == "active":
            await self._pause_workspace(workspace_id)

    @staticmethod
    def _resolve_provider_api_key(provider: str) -> str | None:
        return WorkspaceRegistry._resolve_provider_api_key(provider)

    @staticmethod
    def _resolve_env_vars(key_names: list[str]) -> dict[str, str]:
        return WorkspaceRegistry._resolve_env_vars(key_names)
