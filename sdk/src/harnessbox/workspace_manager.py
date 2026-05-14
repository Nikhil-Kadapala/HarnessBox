"""Workspace management — create, track, and destroy sandbox workspaces.

A workspace is a user-facing abstraction for a branch-based development environment.
Each workspace wraps a Sandbox instance (the infrastructure detail) with metadata
like repo remote, branch name, and lifecycle state.

``WorkspaceConfig`` is a reusable configuration object. ``WorkspaceManager`` is
the registry that maps workspace IDs to live Sandbox instances with branch-based
pooling support.

With storage enabled, workspaces persist across server restarts and can be
resumed from paused state. Use ``WorkspaceManager.create(storage=backend)`` async
factory to enable persistence.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from harnessbox.agent_manager import AgentManager
from harnessbox.lifecycle import InvalidTransitionError, WorkspaceState, validate_transition
from harnessbox.sandbox import Sandbox
from harnessbox.security.policy import SecurityPolicy
from harnessbox.streaming import Attachment, ContentPart, UniversalEvent
from harnessbox.streaming import EventType as StreamEventType
from harnessbox.workspace import Workspace

if TYPE_CHECKING:
    from harnessbox.storage import StorageBackend

logger = logging.getLogger(__name__)

# Import tenacity for retry logic (optional dependency)
try:
    from tenacity import (
        retry,
        retry_if_exception_type,
        stop_after_attempt,
        wait_exponential,
    )

    TENACITY_AVAILABLE = True
except ImportError:
    TENACITY_AVAILABLE = False

# Import E2B exceptions for retry detection
try:
    from e2b.exceptions import TimeoutException
    from e2b_connect.client import ConnectException
except ImportError:

    class TimeoutException(Exception):  # type: ignore
        """Stub for e2b.exceptions.TimeoutException when E2B is not installed."""

    class ConnectException(Exception):  # type: ignore
        """Stub for e2b_connect.client.ConnectException when E2B is not installed."""


@dataclass
class WorkspaceConfig:
    """Reusable workspace configuration. Pass to ``WorkspaceManager.create_workspace()``.

    All fields mirror ``Sandbox.__init__`` params. This exists so configs
    can be stored, serialized, and reused across workspaces.
    """

    provider: str = "e2b"
    api_key: str | None = None
    harness: str = "claude-code"
    model: str | None = None
    system_prompt: str | Path | None = None
    skills: list[str | Path] = field(default_factory=list)
    skill_installs: list[str] = field(default_factory=list)
    plugins: list[str | Path] = field(default_factory=list)
    security_policy: SecurityPolicy | None = None
    workspace: Workspace | None = None
    env_vars: dict[str, str] = field(default_factory=dict)
    files: dict[str, str | Path] | list[str | Path] | None = None
    dirs: list[str] = field(default_factory=list)
    setup_script: str | None = None
    cwd: str | None = None
    timeout: int = 300
    skip_permissions: bool = False
    template: str | None = None
    session_timeout: int = 1800  # 30min default (auto-pause timeout)


@dataclass
class WorkspaceInstance:
    """Live workspace record.

    Contains both in-memory state (sandbox reference, agent manager) and
    persistent metadata (status, branch, cost). Use ``to_record()`` to
    serialize for storage.
    """

    workspace_id: str
    remote: str
    branch: str
    provider: str
    provider_sandbox_id: str | None
    snapshot_id: str | None
    status: str
    created_at: str
    last_active: str
    harness: str = "claude-code"

    # Runtime refs (not persisted)
    sandbox: Sandbox | None = None
    agent_manager: Any = None  # AgentManager, imported lazily to avoid circular import
    workspace_name: str | None = None
    base_branch: str | None = None
    pr_url: str | None = None
    pr_number: int | None = None
    ci_status: str | None = None
    total_cost_usd: float = 0.0

    def to_record(self, config: WorkspaceConfig | None = None) -> dict[str, Any]:
        """Serialize to storage format (primitives only).

        Args:
            config: Original WorkspaceConfig used to create this workspace.
                    Required for new workspaces, optional for updates.

        Returns:
            Dict with workspace metadata suitable for storage.save_workspace().
        """
        config_json = "{}"
        if config is not None:
            # Minimal subset: primitives only, no complex types
            config_json = json.dumps(
                {
                    "provider": config.provider,
                    "harness": config.harness,
                    "timeout": config.timeout,
                    "skip_permissions": config.skip_permissions,
                    "template": config.template,
                    "session_timeout": config.session_timeout,
                }
            )

        return {
            "workspace_id": self.workspace_id,
            "remote": self.remote,
            "branch": self.branch,
            "provider": self.provider,
            "provider_sandbox_id": self.provider_sandbox_id,
            "snapshot_id": self.snapshot_id,
            "harness": self.harness,
            "status": self.status,
            "created_at": self.created_at,
            "last_active": self.last_active,
            "config_json": config_json,
            "workspace_name": self.workspace_name,
            "base_branch": self.base_branch,
            "pr_url": self.pr_url,
            "pr_number": self.pr_number,
            "ci_status": self.ci_status,
            "total_cost_usd": self.total_cost_usd,
        }


class WorkspaceNotFoundError(KeyError):
    """Raised when a workspace ID is not found in the manager registry."""


class WorkspaceManager:
    """Manages multiple sandbox workspaces with branch-based pooling.

    Thread-safe for use from a single asyncio event loop. Each workspace
    gets its own Sandbox instance and asyncio lock for serialized access.

    With storage enabled, workspaces persist across server restarts and
    can be resumed from paused state. Use the async factory
    ``WorkspaceManager.create(storage=backend)`` to enable.
    """

    def __init__(
        self,
        storage: StorageBackend | None = None,
        *,
        auto_pause: bool = True,
        pause_timeout: int = 1800,  # 30min default
    ) -> None:
        self._workspaces: dict[str, WorkspaceInstance] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._storage = storage
        self._workspace_configs: dict[str, WorkspaceConfig] = {}  # For to_record()
        self._auto_pause = auto_pause
        self._pause_timeout = pause_timeout
        self._pause_task: asyncio.Task[None] | None = None

    @classmethod
    async def create(
        cls,
        storage: StorageBackend | None = None,
        **kwargs: Any,
    ) -> WorkspaceManager:
        """Async factory for WorkspaceManager with optional persistence.

        Args:
            storage: Storage backend instance (or None for in-memory only).
            auto_pause: Enable auto-pause for idle workspaces (default: True).
            pause_timeout: Idle timeout in seconds before auto-pause (default: 1800).

        Returns:
            Initialized WorkspaceManager with storage ready (if provided).

        Example:
            >>> from harnessbox._storage import get_storage_backend
            >>> backend_cls = get_storage_backend("sqlite")
            >>> storage = backend_cls()
            >>> mgr = await WorkspaceManager.create(storage=storage)
        """
        mgr = cls(storage, **kwargs)
        if storage:
            await storage.initialize()
            await mgr.load_workspaces()

        # Start auto-pause background task
        if mgr._auto_pause:
            mgr._pause_task = asyncio.create_task(mgr._run_auto_pause_task())

        return mgr

    async def create_workspace(
        self,
        config: WorkspaceConfig,
        *,
        workspace_id: str | None = None,
        event_handler: Any = None,
    ) -> WorkspaceInstance:
        """Create a new workspace with live sandbox.

        If storage is enabled, the workspace is persisted after creation.
        """
        wid = workspace_id or str(uuid.uuid4())
        lock = asyncio.Lock()

        sandbox = Sandbox(
            client=config.provider,
            api_key=config.api_key,
            harness=config.harness,
            model=config.model,
            system_prompt=config.system_prompt,
            skills=config.skills or None,
            skill_installs=config.skill_installs or None,
            plugins=config.plugins or None,
            security_policy=config.security_policy,
            workspace=config.workspace,
            env_vars=config.env_vars or None,
            files=config.files,
            dirs=config.dirs or None,
            setup_script=config.setup_script,
            cwd=config.cwd,
            timeout=config.timeout,
            skip_permissions=config.skip_permissions,
            template=config.template,
            event_handler=event_handler,
            session_timeout=config.session_timeout,
            session_lock=lock,
            storage=self._storage,
            session_id=wid,
        )
        await sandbox.setup()

        # Extract workspace metadata
        workspace_name = None
        branch = ""
        base_branch = None
        remote = ""

        if config.workspace:
            if hasattr(config.workspace, "clone_dir_name"):
                workspace_name = config.workspace.clone_dir_name
            if hasattr(config.workspace, "branch"):
                branch = config.workspace.branch
            if hasattr(config.workspace, "base_branch"):
                base_branch = config.workspace.base_branch
            if hasattr(config.workspace, "remote"):
                remote = config.workspace.remote

        # Create agent manager
        agent_mgr = AgentManager(sandbox)

        info = WorkspaceInstance(
            workspace_id=wid,
            remote=remote,
            branch=branch,
            provider=config.provider,
            provider_sandbox_id=None,  # Set after first pause
            snapshot_id=None,
            status=WorkspaceState.ACTIVE.value,
            created_at=datetime.now(timezone.utc).isoformat(),
            last_active=datetime.now(timezone.utc).isoformat(),
            harness=config.harness,
            sandbox=sandbox,
            agent_manager=agent_mgr,
            workspace_name=workspace_name,
            base_branch=base_branch,
        )

        self._workspaces[wid] = info
        self._locks[wid] = lock
        self._workspace_configs[wid] = config

        # Persist to storage
        if self._storage:
            try:
                await self._storage.save_workspace(info.to_record(config))
            except Exception as e:
                logger.error(f"Failed to persist workspace {wid}: {e}")

        return info

    def get_workspace(self, workspace_id: str) -> WorkspaceInstance:
        """Return the workspace instance by ID, raising WorkspaceNotFoundError if missing."""
        if workspace_id not in self._workspaces:
            raise WorkspaceNotFoundError(f"Workspace not found: {workspace_id}")
        return self._workspaces[workspace_id]

    def list_workspaces(self) -> list[WorkspaceInstance]:
        """List all workspaces currently in memory (live + loaded from storage)."""
        return list(self._workspaces.values())

    async def load_workspaces(self, limit: int = 100) -> None:
        """Load recent workspaces from storage into memory (view-only).

        Args:
            limit: Maximum number of workspaces to load (default: 100).

        Note:
            Loaded workspaces have sandbox=None (view-only). They appear in
            list_workspaces() but cannot receive new prompts until resumed.
        """
        if not self._storage:
            return

        try:
            records = await self._storage.list_workspaces(limit=limit)
            for record in records:
                wid = record["workspace_id"]
                if wid in self._workspaces:
                    continue  # Skip if already loaded (live workspace)

                # Validate config_json is parseable
                try:
                    _ = json.loads(record.get("config_json", "{}"))
                except json.JSONDecodeError:
                    logger.warning(f"Malformed config_json for workspace {wid}, skipping")
                    continue

                # Create view-only WorkspaceInstance
                info = WorkspaceInstance(
                    workspace_id=wid,
                    remote=record.get("remote", ""),
                    branch=record.get("branch", ""),
                    provider=record["provider"],
                    provider_sandbox_id=record.get("provider_sandbox_id"),
                    snapshot_id=record.get("snapshot_id"),
                    status=record["status"],
                    created_at=record["created_at"],
                    last_active=record.get("last_active", record["created_at"]),
                    harness=record["harness"],
                    sandbox=None,  # No live sandbox
                    agent_manager=None,
                    workspace_name=record.get("workspace_name"),
                    base_branch=record.get("base_branch"),
                    pr_url=record.get("pr_url"),
                    pr_number=record.get("pr_number"),
                    ci_status=record.get("ci_status"),
                    total_cost_usd=record.get("total_cost_usd", 0.0),
                )
                self._workspaces[wid] = info
                # No lock for view-only workspaces

            logger.info(f"Loaded {len(records)} workspaces from storage")
        except Exception as e:
            logger.error(f"Failed to load workspaces from storage: {e}")

    async def prompt(
        self,
        workspace_id: str,
        prompt: str,
        *,
        conversation_id: str | None = None,
        attachments: list[Attachment] | None = None,
    ) -> AsyncGenerator[UniversalEvent, None]:
        """Send prompt to workspace (auto-resumes if paused).

        Args:
            workspace_id: Target workspace
            prompt: Prompt text
            conversation_id: Specific conversation (generates UUID if None)
            attachments: Files/images to write to sandbox and reference in prompt
        """
        import base64

        info = self.get_workspace(workspace_id)

        if info.sandbox is None:
            raise ValueError(
                f"Workspace {workspace_id} is view-only (no live sandbox). "
                "Cannot send prompts to workspaces loaded from storage."
            )

        # Auto-resume if paused
        if info.status == WorkspaceState.PAUSED.value:
            await self._resume_workspace(workspace_id)

        # Route to agent manager
        if not info.agent_manager:
            raise ValueError(f"Workspace {workspace_id} has no agent manager")

        # Generate conversation_id if not provided
        if conversation_id is None:
            conversation_id = str(uuid.uuid4())

        # Update last_active
        info.last_active = datetime.now(timezone.utc).isoformat()
        if self._storage:
            await self._storage.update_workspace(workspace_id, last_active=info.last_active)

        async with self._locks[workspace_id]:
            # Write attachments to sandbox and build metadata
            resolved_attachments: list[Attachment] = []
            if attachments:
                cwd = info.sandbox._cwd or "/workspace"
                for att in attachments:
                    sandbox_path = f"{cwd}/.attachments/{att.attachment_id}/{att.filename}"
                    await info.sandbox._provider.make_dir(
                        f"{cwd}/.attachments/{att.attachment_id}"
                    )
                    raw_data = base64.b64decode(
                        att.data_b64 or ""
                    ) if att.data_b64 else (
                        Path(att.storage_path).read_bytes() if att.storage_path else b""
                    )
                    if raw_data:
                        await info.sandbox._provider.write_file(sandbox_path, raw_data)
                    resolved_attachments.append(Attachment(
                        attachment_id=att.attachment_id,
                        filename=att.filename,
                        mime_type=att.mime_type,
                        size_bytes=att.size_bytes,
                        data_b64=att.data_b64,
                        storage_path=att.storage_path,
                        sandbox_path=sandbox_path,
                    ))

            # Emit USER_PROMPT event
            attachment_meta = [
                {
                    "attachment_id": a.attachment_id,
                    "filename": a.filename,
                    "mime_type": a.mime_type,
                    "size_bytes": a.size_bytes,
                    "sandbox_path": a.sandbox_path,
                    **({"data_b64": a.data_b64} if a.data_b64 and a.size_bytes < 1024 * 1024 else {}),
                }
                for a in resolved_attachments
            ]
            user_prompt_event = UniversalEvent(
                event_id=str(uuid.uuid4()),
                sequence=0,
                timestamp=datetime.now(timezone.utc).isoformat(),
                session_id=conversation_id,
                event_type=StreamEventType.USER_PROMPT,
                content=(ContentPart(type="text", text=prompt),),
                metadata={
                    "conversation_id": conversation_id,
                    **({"attachments": attachment_meta} if attachment_meta else {}),
                },
            )
            if info.sandbox._event_buffer:
                await info.sandbox._event_buffer.push(user_prompt_event)
            yield user_prompt_event

            # Augment prompt with file references for the agent
            augmented_prompt = prompt
            if resolved_attachments:
                file_list = "\n".join(
                    f"- {a.sandbox_path}" for a in resolved_attachments
                )
                augmented_prompt = f"{prompt}\n\n[Attached files written to sandbox:\n{file_list}]"

            # Save conversation on first agent event
            first_event = True
            async for event in info.agent_manager.send_message(
                conversation_id, augmented_prompt
            ):
                if (
                    event.event_type == "error"
                    and event.metadata.get("error_code") == "SANDBOX_DEAD"
                ):
                    info.status = WorkspaceState.FAILED.value

                if event.cost_usd is not None:
                    info.total_cost_usd = event.cost_usd

                if first_event and self._storage:
                    first_event = False
                    try:
                        await self._storage.save_conversation(
                            {
                                "conversation_id": conversation_id,
                                "workspace_id": workspace_id,
                                "agent_type": info.harness,
                                "title": prompt[:50],
                                "last_active": datetime.now(timezone.utc).isoformat(),
                            }
                        )
                    except Exception as e:
                        logger.error(f"Failed to save conversation {conversation_id}: {e}")

                yield event

    def find_by_repo_branch(self, remote: str, branch: str) -> WorkspaceInstance | None:
        """Find a workspace matching a repo remote URL and branch name."""
        for info in self._workspaces.values():
            if info.remote == remote and info.branch == branch:
                return info
        return None

    async def get_or_create_workspace(
        self,
        remote: str,
        branch: str,
        *,
        config: WorkspaceConfig | None = None,
        workspace_id: str | None = None,
    ) -> WorkspaceInstance:
        """Get existing paused workspace or create new one.

        Searches for PAUSED workspace matching (remote, branch). If found,
        resumes it. Otherwise creates new workspace.

        Args:
            remote: Git remote URL
            branch: Git branch name
            config: WorkspaceConfig (required if creating new workspace)
            workspace_id: Optional workspace_id for new workspace

        Returns:
            WorkspaceInstance (either resumed or newly created)

        Raises:
            ValueError: If no match found and config is None
        """
        # Check in-memory pool first
        for info in self._workspaces.values():
            if (
                info.status == WorkspaceState.PAUSED.value
                and info.remote == remote
                and info.branch == branch
            ):
                logger.info(
                    f"Pool hit: resuming workspace {info.workspace_id} for {remote}@{branch}"
                )
                await self._resume_workspace(info.workspace_id)
                return info

        # Check storage (historical paused workspaces)
        if self._storage:
            candidates = await self._storage.list_workspaces(
                status=WorkspaceState.PAUSED.value,
                remote=remote,
                branch=branch,
                limit=1,
            )
            if candidates:
                record = candidates[0]
                wid = record["workspace_id"]

                logger.info(
                    f"Pool hit from storage: hydrating workspace {wid} for {remote}@{branch}"
                )

                # Hydrate workspace instance
                info = await self._hydrate_workspace(record)
                self._workspaces[wid] = info
                self._locks[wid] = asyncio.Lock()

                await self._resume_workspace(wid)
                return info

        # No match, create new
        if config is None:
            raise ValueError(
                f"No paused workspace found for {remote}@{branch} and config not provided. "
                "Cannot create new workspace."
            )

        logger.info(f"Pool miss: creating new workspace for {remote}@{branch}")
        return await self.create_workspace(config, workspace_id=workspace_id)

    async def _hydrate_workspace(self, record: dict[str, Any]) -> WorkspaceInstance:
        """Recreate WorkspaceInstance from storage record.

        Note: Does NOT call setup() — sandbox already exists, will resume on demand.
        """
        # Parse config_json
        config_dict = json.loads(record.get("config_json", "{}"))

        sandbox = Sandbox(
            client=record["provider"],
            harness=record["harness"],
            model=config_dict.get("model"),
            timeout=config_dict.get("timeout", 300),
            skip_permissions=config_dict.get("skip_permissions", False),
            template=config_dict.get("template"),
        )
        # IMPORTANT: Do not call sandbox.setup() — sandbox already exists

        # Create AgentManager
        agent_mgr = AgentManager(sandbox)

        return WorkspaceInstance(
            workspace_id=record["workspace_id"],
            remote=record.get("remote", ""),
            branch=record.get("branch", ""),
            provider=record["provider"],
            provider_sandbox_id=record.get("provider_sandbox_id"),
            snapshot_id=record.get("snapshot_id"),
            status=record["status"],
            created_at=record["created_at"],
            last_active=record.get("last_active", record["created_at"]),
            harness=record["harness"],
            sandbox=sandbox,
            agent_manager=agent_mgr,
            workspace_name=record.get("workspace_name"),
            base_branch=record.get("base_branch"),
            pr_url=record.get("pr_url"),
            pr_number=record.get("pr_number"),
            ci_status=record.get("ci_status"),
            total_cost_usd=record.get("total_cost_usd", 0.0),
        )

    def transition_workspace(self, workspace_id: str, target_state: str) -> WorkspaceInstance:
        """Transition workspace to a new state with validation.

        If storage is enabled, the state change is persisted.
        """
        info = self.get_workspace(workspace_id)
        current = WorkspaceState(info.status)
        target = WorkspaceState(target_state)
        if not validate_transition(current, target):
            raise InvalidTransitionError(current, target)
        info.status = target.value

        # Persist state change
        if self._storage:
            asyncio.create_task(
                self._storage.update_workspace(
                    workspace_id,
                    status=target.value,
                )
            )

        return info

    async def destroy_workspace(self, workspace_id: str) -> None:
        """Destroy a workspace and kill its sandbox.

        If storage is enabled, the workspace is marked as failed (not deleted).
        """
        info = self.get_workspace(workspace_id)
        async with self._locks[workspace_id]:
            # Shutdown all agents
            if info.agent_manager:
                await info.agent_manager.shutdown_all()

            # Kill sandbox
            if info.sandbox:
                await info.sandbox.kill()

            info.status = WorkspaceState.FAILED.value

        # Persist final state
        if self._storage:
            try:
                await self._storage.update_workspace(
                    workspace_id,
                    status=WorkspaceState.FAILED.value,
                )
            except Exception as e:
                logger.error(f"Failed to persist destroyed workspace {workspace_id}: {e}")

        self._workspaces.pop(workspace_id, None)
        self._locks.pop(workspace_id, None)
        self._workspace_configs.pop(workspace_id, None)

    async def _run_auto_pause_task(self) -> None:
        """Background task: scan for idle workspaces every 60 seconds."""
        while True:
            await asyncio.sleep(60)
            now = datetime.now(timezone.utc)

            for wid, info in list(self._workspaces.items()):
                if info.status != WorkspaceState.ACTIVE.value:
                    continue

                # Parse last_active
                try:
                    last_active = datetime.fromisoformat(info.last_active)
                    idle_seconds = (now - last_active).total_seconds()

                    if idle_seconds > self._pause_timeout:
                        try:
                            await self._pause_workspace(wid)
                        except Exception as e:
                            logger.error(f"Auto-pause failed for {wid}: {e}")
                except (ValueError, TypeError) as e:
                    logger.warning(f"Invalid last_active timestamp for {wid}: {e}")

    async def _pause_workspace(self, workspace_id: str) -> None:
        """Pause workspace and create snapshot."""
        info = self.get_workspace(workspace_id)
        if not info.sandbox:
            return

        async with self._locks[workspace_id]:
            # Stop all agents
            if info.agent_manager:
                await info.agent_manager.shutdown_all()

            # Create snapshot (captures filesystem including ~/.claude/sessions/)
            try:
                snapshot_id = await info.sandbox.create_snapshot()
            except Exception as e:
                logger.warning(f"Failed to create snapshot for {workspace_id}: {e}")
                snapshot_id = None

            # Pause sandbox
            provider_sandbox_id = await info.sandbox.pause()

            info.provider_sandbox_id = provider_sandbox_id
            info.snapshot_id = snapshot_id
            info.status = WorkspaceState.PAUSED.value

            # Persist
            if self._storage:
                await self._storage.update_workspace(
                    workspace_id,
                    provider_sandbox_id=provider_sandbox_id,
                    snapshot_id=snapshot_id,
                    status=WorkspaceState.PAUSED.value,
                )

            logger.info(f"Paused workspace {workspace_id}")

    def _is_sandbox_expired(self, error: Exception) -> bool:
        """Detect if error indicates sandbox no longer exists."""
        error_str = str(error).lower()
        return any(
            pattern in error_str
            for pattern in [
                "sandbox was not found",
                "404",
                "not found",
                "does not exist",
            ]
        )

    async def _try_resume_sandbox(self, info: WorkspaceInstance) -> None:
        """Attempt to resume sandbox with retries.

        Raises TimeoutException or ConnectException if all retries fail.
        """
        if not info.sandbox or not info.provider_sandbox_id:
            raise ValueError("Cannot resume: sandbox or provider_sandbox_id is None")

        if TENACITY_AVAILABLE:
            # Use tenacity retry decorator
            @retry(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=1, min=2, max=10),
                retry=retry_if_exception_type((TimeoutException, ConnectException)),
            )
            async def _resume_with_retry() -> None:
                await info.sandbox.resume(info.provider_sandbox_id)  # type: ignore

            await _resume_with_retry()
        else:
            # Fallback: simple retry without tenacity
            for attempt in range(3):
                try:
                    await info.sandbox.resume(info.provider_sandbox_id)  # type: ignore
                    return
                except (TimeoutException, ConnectException) as e:
                    if attempt == 2:  # Last attempt
                        raise
                    logger.warning(f"Resume attempt {attempt + 1} failed: {e}, retrying...")
                    await asyncio.sleep(2**attempt)  # Exponential backoff

    async def _resume_workspace(self, workspace_id: str) -> None:
        """Resume paused workspace with transparent snapshot recovery."""
        info = self.get_workspace(workspace_id)
        if info.status != WorkspaceState.PAUSED.value:
            return

        if not info.sandbox:
            raise ValueError(
                f"Workspace {workspace_id} is view-only (no live sandbox). "
                "Cannot resume workspaces loaded from storage."
            )

        async with self._locks[workspace_id]:
            try:
                # Try to resume with retries
                await self._try_resume_sandbox(info)
            except (TimeoutException, ConnectException) as e:
                # Check if sandbox expired
                if self._is_sandbox_expired(e):
                    if not info.snapshot_id:
                        raise ValueError(
                            f"Workspace {workspace_id} expired and has no snapshot"
                        ) from e

                    # Create new sandbox from snapshot
                    logger.warning(
                        f"Sandbox {info.provider_sandbox_id} expired, recovering from snapshot {info.snapshot_id}"
                    )
                    # Note: This requires creating a new Sandbox instance from snapshot
                    # For now, we re-raise. Full snapshot recovery requires provider support.
                    raise ValueError(
                        f"Snapshot recovery not yet implemented. Workspace {workspace_id} is unrecoverable."
                    ) from e
                else:
                    raise

            info.status = WorkspaceState.ACTIVE.value
            info.last_active = datetime.now(timezone.utc).isoformat()

            # Persist
            if self._storage:
                await self._storage.update_workspace(
                    workspace_id,
                    status=WorkspaceState.ACTIVE.value,
                    last_active=info.last_active,
                )

            logger.info(f"Resumed workspace {workspace_id}")

    async def shutdown_all(self) -> None:
        """Destroy all active workspaces and cancel background tasks."""
        # Stop auto-pause task
        if self._pause_task:
            self._pause_task.cancel()
            try:
                await self._pause_task
            except asyncio.CancelledError:
                pass

        # Destroy all workspaces
        for wid in list(self._workspaces):
            try:
                await self.destroy_workspace(wid)
            except Exception:
                pass
