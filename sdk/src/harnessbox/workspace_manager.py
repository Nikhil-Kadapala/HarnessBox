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
from typing import TYPE_CHECKING, Any, cast

from harnessbox.agent_manager import AgentManager
from harnessbox.lifecycle import (
    InvalidTransitionError,
    RuntimeState,
    WorkflowState,
    validate_runtime_transition,
    validate_workflow_transition,
)
from harnessbox.providers import SandboxDeadError, SandboxProvider
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

    provider: str | SandboxProvider = "e2b"
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
    branch_label: str = ""
    remote_label: str = ""


@dataclass
class WorkspaceInstance:
    """Workspace record — in-memory state + persistent metadata.

    State is split into two independent dimensions:
    - runtime_state: sandbox infrastructure (STARTING/ACTIVE/PAUSED/ENDING/ENDED/FAILED)
    - workflow_state: project lifecycle (BACKLOG/IN_PROGRESS/IN_REVIEW/MERGED/ARCHIVED)
    """

    workspace_id: str
    remote: str
    branch: str
    provider: str
    provider_sandbox_id: str | None
    snapshot_id: str | None
    runtime_state: str
    workflow_state: str
    created_at: str
    last_active: str
    harness: str = "claude-code"

    # Runtime refs (not persisted)
    sandbox_conn: Sandbox | None = None
    """Ephemeral client handle to the provider sandbox.

    None means the process hasn't established a connection yet (e.g. after
    server restart or storage hydration). The logical sandbox still exists —
    provider_sandbox_id always identifies it. The connection is created lazily
    via WorkspaceManager._ensure_sandbox() → _connect_sandbox() on first use.
    """
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
            provider_name = config.provider if isinstance(config.provider, str) else "custom"
            config_json = json.dumps(
                {
                    "provider": provider_name,
                    "harness": config.harness,
                    "timeout": config.timeout,
                    "skip_permissions": config.skip_permissions,
                    "template": config.template,
                    "session_timeout": config.session_timeout,
                    "env_var_keys": list(config.env_vars.keys()) if config.env_vars else [],
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
            "runtime_state": self.runtime_state,
            "workflow_state": self.workflow_state,
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
        # Per-workspace idle sleep tasks (replaces global 60s scan loop).
        # Each entry is an asyncio.Task that fires _pause_workspace() after
        # pause_timeout seconds of idle. Cancelled/restarted on turn boundaries.
        self._idle_timers: dict[str, asyncio.Task[None]] = {}
        # Count of in-flight turns per workspace (across all concurrent conversations).
        # The idle timer only restarts when this count drops to zero, ensuring we
        # never auto-pause a workspace that still has an active agent turn running.
        self._active_turns: dict[str, int] = {}

    def _ensure_lock(self, workspace_id: str) -> asyncio.Lock:
        """Return the per-workspace lock, creating it if absent."""
        if workspace_id not in self._locks:
            self._locks[workspace_id] = asyncio.Lock()
        return self._locks[workspace_id]

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

        if not branch:
            branch = config.branch_label
        if not remote:
            remote = config.remote_label

        # Create agent manager
        agent_mgr = AgentManager(sandbox)

        provider_name = config.provider if isinstance(config.provider, str) else "custom"

        info = WorkspaceInstance(
            workspace_id=wid,
            remote=remote,
            branch=branch,
            provider=provider_name,
            provider_sandbox_id=sandbox.sandbox_id,
            snapshot_id=None,
            runtime_state=RuntimeState.ACTIVE.value,
            workflow_state=WorkflowState.IN_PROGRESS.value,
            created_at=datetime.now(timezone.utc).isoformat(),
            last_active=datetime.now(timezone.utc).isoformat(),
            harness=config.harness,
            sandbox_conn=sandbox,
            agent_manager=agent_mgr,
            workspace_name=workspace_name,
            base_branch=base_branch,
        )

        self._workspaces[wid] = info
        self._locks[wid] = lock
        self._workspace_configs[wid] = config

        # Persist to storage (skip when provider is a custom instance —
        # hydration cannot recreate it from a stored record).
        if self._storage and isinstance(config.provider, str):
            try:
                await self._storage.save_workspace(info.to_record(config))
            except Exception as e:
                logger.error(f"Failed to persist workspace {wid}: {e}")

        # Start idle countdown — workspace starts idle (no turn in flight yet)
        if self._auto_pause:
            self._start_idle_timer(wid)

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
        """Load recent workspaces from storage into memory.

        Args:
            limit: Maximum number of workspaces to load (default: 100).

        Note:
            Loaded workspaces start with sandbox_conn=None (disconnected). The
            connection is established lazily on first prompt via _ensure_sandbox().
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

                info = WorkspaceInstance(
                    workspace_id=wid,
                    remote=record.get("remote", ""),
                    branch=record.get("branch", ""),
                    provider=record["provider"],
                    provider_sandbox_id=record.get("provider_sandbox_id"),
                    snapshot_id=record.get("snapshot_id"),
                    runtime_state=record["runtime_state"],
                    workflow_state=record.get("workflow_state", WorkflowState.BACKLOG.value),
                    created_at=record["created_at"],
                    last_active=record.get("last_active", record["created_at"]),
                    harness=record["harness"],
                    sandbox_conn=None,
                    agent_manager=None,
                    workspace_name=record.get("workspace_name"),
                    base_branch=record.get("base_branch"),
                    pr_url=record.get("pr_url"),
                    pr_number=record.get("pr_number"),
                    ci_status=record.get("ci_status"),
                    total_cost_usd=record.get("total_cost_usd", 0.0),
                )
                self._workspaces[wid] = info

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
        """Send prompt to workspace.

        Ensures the sandbox is connected before forwarding. If the sandbox
        connection is cold (loaded from storage) or paused, it is reconnected
        lazily. No pre-flight status checks on every request — errors from
        the provider trigger reconnection.

        Args:
            workspace_id: Target workspace
            prompt: Prompt text
            conversation_id: Specific conversation (generates UUID if None)
            attachments: Files/images to write to sandbox and reference in prompt
        """
        import base64

        info = self.get_workspace(workspace_id)

        # Ensure sandbox is connected (lazy init for cold/paused workspaces)
        await self._ensure_sandbox(workspace_id)

        # Generate conversation_id if not provided
        if conversation_id is None:
            conversation_id = str(uuid.uuid4())

        # Turn starting — cancel idle countdown and bump the in-flight counter.
        # We only restart the timer once ALL concurrent turns have completed,
        # so a workspace with multiple parallel conversations doesn't get paused
        # while one conversation is still active.
        self._cancel_idle_timer(workspace_id)
        self._active_turns[workspace_id] = self._active_turns.get(workspace_id, 0) + 1
        # Per-invocation flag: True once TURN_ENDED or SESSION_ENDED fires normally.
        # The finally block uses this to avoid double-decrementing when concurrent
        # turns are running (shared counter would still be >0 after normal completion).
        turn_ended_seen = False

        # Update last_active
        info.last_active = datetime.now(timezone.utc).isoformat()
        if self._storage:
            await self._storage.update_workspace(workspace_id, last_active=info.last_active)

        try:
            async with self._locks[workspace_id]:
                # Write attachments to sandbox and build metadata
                resolved_attachments: list[Attachment] = []
                if attachments:
                    cwd = info.sandbox_conn._cwd or "/workspace"
                    for att in attachments:
                        safe_name = Path(att.filename).name or "attachment"
                        sandbox_path = f"{cwd}/.attachments/{att.attachment_id}/{safe_name}"
                        await info.sandbox_conn._provider.make_dir(
                            f"{cwd}/.attachments/{att.attachment_id}"
                        )
                        raw_data = (
                            base64.b64decode(att.data_b64 or "")
                            if att.data_b64
                            else (Path(att.storage_path).read_bytes() if att.storage_path else b"")
                        )
                        if raw_data:
                            await info.sandbox_conn._provider.write_file(sandbox_path, raw_data)
                        resolved_attachments.append(
                            Attachment(
                                attachment_id=att.attachment_id,
                                filename=att.filename,
                                mime_type=att.mime_type,
                                size_bytes=att.size_bytes,
                                data_b64=att.data_b64,
                                storage_path=att.storage_path,
                                sandbox_path=sandbox_path,
                            )
                        )

                # Emit USER_PROMPT event
                attachment_meta = [
                    {
                        "attachment_id": a.attachment_id,
                        "filename": a.filename,
                        "mime_type": a.mime_type,
                        "size_bytes": a.size_bytes,
                        "sandbox_path": a.sandbox_path,
                        **(
                            {"data_b64": a.data_b64}
                            if a.data_b64 and a.size_bytes < 1024 * 1024
                            else {}
                        ),
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
                if info.sandbox_conn._event_buffer:
                    user_prompt_event = await info.sandbox_conn._event_buffer.push(
                        user_prompt_event
                    )
                yield user_prompt_event

                # Augment prompt with file references for the agent
                augmented_prompt = prompt
                if resolved_attachments:
                    file_list = "\n".join(f"- {a.sandbox_path}" for a in resolved_attachments)
                    augmented_prompt = (
                        f"{prompt}\n\n[Attached files written to sandbox:\n{file_list}]"
                    )

                # Save conversation on first agent event
                first_event = True
                async for event in info.agent_manager.send_message(
                    conversation_id, augmented_prompt
                ):
                    if (
                        event.event_type == "error"
                        and event.metadata.get("error_code") == "SANDBOX_DEAD"
                    ):
                        info.runtime_state = RuntimeState.FAILED.value

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

                    # Turn completed — decrement active-turn counter and restart
                    # idle countdown only when all concurrent turns are done.
                    if event.event_type in (
                        StreamEventType.TURN_ENDED,
                        StreamEventType.SESSION_ENDED,
                    ):
                        turn_ended_seen = True
                        info.last_active = datetime.now(timezone.utc).isoformat()
                        if self._storage:
                            try:
                                await self._storage.update_workspace(
                                    workspace_id, last_active=info.last_active
                                )
                            except Exception as e:
                                logger.error(
                                    f"Failed to persist last_active for {workspace_id}: {e}"
                                )
                        active = max(0, self._active_turns.get(workspace_id, 1) - 1)
                        self._active_turns[workspace_id] = active
                        if active == 0 and self._auto_pause:
                            self._start_idle_timer(workspace_id)
        finally:
            # Safety net: decrement the counter if the turn errored before TURN_ENDED
            # fired (turn_ended_seen=False). Skip if TURN_ENDED already ran to avoid
            # double-decrementing the shared counter for concurrent turns.
            if not turn_ended_seen:
                active = max(0, self._active_turns.get(workspace_id, 1) - 1)
                self._active_turns[workspace_id] = active
                if active == 0 and self._auto_pause:
                    ws = self._workspaces.get(workspace_id)
                    if ws and ws.runtime_state == RuntimeState.ACTIVE.value:
                        self._start_idle_timer(workspace_id)

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
                info.runtime_state == RuntimeState.PAUSED.value
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
                runtime_state=RuntimeState.PAUSED.value,
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
            runtime_state=record["runtime_state"],
            workflow_state=record.get("workflow_state", WorkflowState.BACKLOG.value),
            created_at=record["created_at"],
            last_active=record.get("last_active", record["created_at"]),
            harness=record["harness"],
            sandbox_conn=sandbox,
            agent_manager=agent_mgr,
            workspace_name=record.get("workspace_name"),
            base_branch=record.get("base_branch"),
            pr_url=record.get("pr_url"),
            pr_number=record.get("pr_number"),
            ci_status=record.get("ci_status"),
            total_cost_usd=record.get("total_cost_usd", 0.0),
        )

    @staticmethod
    def _resolve_provider_api_key(provider: str) -> str | None:
        """Resolve provider API key from environment or CLI config files.

        Secrets are never stored in the database — they are re-resolved from the
        host environment at revive time, matching the behavior of workspace creation.
        """
        import os

        key_names = {
            "e2b": ["E2B_API_KEY", "E2B_ACCESS_TOKEN"],
        }

        for key_name in key_names.get(provider, []):
            val = os.environ.get(key_name, "").strip()
            if val:
                return val

        if provider == "e2b":
            try:
                config_path = Path.home() / ".e2b" / "config.json"
                if config_path.is_file():
                    data = json.loads(config_path.read_text(encoding="utf-8"))
                    for field in ("teamApiKey", "accessToken"):
                        val = (data.get(field) or "").strip()
                        if val:
                            return val
            except Exception:
                pass

        return None

    @staticmethod
    def _resolve_env_vars(key_names: list[str]) -> dict[str, str]:
        """Resolve environment variable values from the host by key name.

        Only keys present in the host environment are included in the result.
        Missing keys are silently skipped (the agent will surface the error
        if a required var is absent).
        """
        import os

        resolved: dict[str, str] = {}
        for key in key_names:
            val = os.environ.get(key, "").strip()
            if val:
                resolved[key] = val
        return resolved

    async def _ensure_sandbox(self, workspace_id: str) -> None:
        """Ensure workspace has a live sandbox connection.

        Handles all cold-start cases without pre-flight status checks:
        - sandbox_conn=None (loaded from storage) → reconnect from stored config
        - runtime_state=paused (connection exists but sandbox is suspended) → resume

        If the workspace is already active with a live connection, this is a no-op.
        """
        info = self.get_workspace(workspace_id)

        if info.sandbox_conn is None:
            await self._connect_sandbox(workspace_id)
        elif info.runtime_state == RuntimeState.PAUSED.value:
            await self._resume_workspace(workspace_id)

    async def _connect_sandbox(self, workspace_id: str) -> None:
        """Reconnect a workspace to its sandbox from stored configuration.

        Constructs a fresh Sandbox + AgentManager using config_json from storage,
        then reconnects via provider_sandbox_id. Falls back to snapshot recovery
        if the original sandbox has expired.
        """
        if not self._storage:
            raise ValueError(
                f"Workspace {workspace_id} has no live sandbox and no storage backend "
                "is configured — cannot reconnect without stored configuration."
            )

        async with self._ensure_lock(workspace_id):
            info = self.get_workspace(workspace_id)

            # Re-check under lock — another concurrent prompt may have connected already
            if info.sandbox_conn is not None:
                return

            record = await self._storage.get_workspace(workspace_id)
            if record is None:
                raise ValueError(
                    f"Workspace {workspace_id} not found in storage — cannot reconnect."
                )

            try:
                config_dict = json.loads(record.get("config_json", "{}"))
            except json.JSONDecodeError as e:
                raise ValueError(
                    f"Workspace {workspace_id} has malformed config_json in storage."
                ) from e

            api_key = self._resolve_provider_api_key(record["provider"])

            if api_key is None and record["provider"] == "e2b":
                raise ValueError(
                    f"Cannot reconnect workspace {workspace_id}: E2B API key not found. "
                    "Set E2B_API_KEY env var or configure ~/.e2b/config.json."
                )

            sandbox = Sandbox(
                client=record["provider"],
                api_key=api_key,
                harness=record["harness"],
                model=config_dict.get("model"),
                timeout=config_dict.get("timeout", 300),
                skip_permissions=config_dict.get("skip_permissions", False),
                template=config_dict.get("template"),
                session_timeout=config_dict.get("session_timeout", 1800),
                session_lock=self._locks[workspace_id],
                storage=self._storage,
                session_id=workspace_id,
            )

            provider_sandbox_id = info.provider_sandbox_id or record.get("provider_sandbox_id")
            snapshot_id = info.snapshot_id or record.get("snapshot_id")

            env_var_keys = config_dict.get("env_var_keys") or list(
                config_dict.get("env_vars", {}).keys()
            )
            resolved_env_vars = self._resolve_env_vars(env_var_keys)

            if provider_sandbox_id:
                try:
                    await sandbox.resume(provider_sandbox_id)
                except (TimeoutException, ConnectException, SandboxDeadError) as e:
                    if self._is_sandbox_expired(e) or isinstance(e, SandboxDeadError):
                        if not snapshot_id:
                            raise ValueError(
                                f"Workspace {workspace_id} sandbox expired and has no "
                                "snapshot. Session is unrecoverable."
                            ) from e
                        logger.warning(
                            "Sandbox %s expired, recovering from snapshot %s",
                            provider_sandbox_id,
                            snapshot_id,
                        )
                        await self._create_from_snapshot(
                            sandbox, config_dict, snapshot_id, env_vars=resolved_env_vars
                        )
                    else:
                        raise
            elif snapshot_id:
                await self._create_from_snapshot(
                    sandbox, config_dict, snapshot_id, env_vars=resolved_env_vars
                )
            else:
                raise ValueError(
                    f"Workspace {workspace_id} has no provider_sandbox_id or snapshot_id. "
                    "Cannot reconnect without a way to reach the sandbox."
                )

            agent_mgr = AgentManager(sandbox)

            self._workspace_configs[workspace_id] = WorkspaceConfig(
                provider=record["provider"],
                harness=record["harness"],
                model=config_dict.get("model"),
                timeout=config_dict.get("timeout", 300),
                skip_permissions=config_dict.get("skip_permissions", False),
                template=config_dict.get("template"),
                session_timeout=config_dict.get("session_timeout", 1800),
                env_vars=resolved_env_vars,
            )

            info.sandbox_conn = sandbox
            info.agent_manager = agent_mgr
            info.runtime_state = RuntimeState.ACTIVE.value
            info.last_active = datetime.now(timezone.utc).isoformat()
            info.provider_sandbox_id = sandbox.sandbox_id

        if self._storage:
            await self._storage.update_workspace(
                workspace_id,
                runtime_state=RuntimeState.ACTIVE.value,
                last_active=info.last_active,
                provider_sandbox_id=info.provider_sandbox_id,
            )

        if self._auto_pause:
            self._start_idle_timer(workspace_id)

        logger.info(f"Reconnected workspace {workspace_id}")

    @staticmethod
    async def _create_from_snapshot(
        sandbox: Sandbox,
        config_dict: dict[str, Any],
        snapshot_id: str,
        *,
        env_vars: dict[str, str] | None = None,
    ) -> None:
        """Create a sandbox from a snapshot and transition to ACTIVE state."""
        resolved_vars = env_vars if env_vars is not None else config_dict.get("env_vars", {})
        timeout = config_dict.get("timeout", 300)
        await cast(Any, sandbox._provider).create(
            env_vars=resolved_vars,
            timeout=timeout,
            snapshot_id=snapshot_id,
        )
        # provider.create() leaves Sandbox in STARTING state — transition to ACTIVE
        # since we're bypassing the normal setup() pipeline.
        sandbox._transition(RuntimeState.ACTIVE)

    def transition_runtime(self, workspace_id: str, target_state: str) -> WorkspaceInstance:
        """Transition workspace runtime state with validation.

        If storage is enabled, the state change is persisted.
        """
        info = self.get_workspace(workspace_id)
        current = RuntimeState(info.runtime_state)
        target = RuntimeState(target_state)
        if not validate_runtime_transition(current, target):
            raise InvalidTransitionError(current, target)
        info.runtime_state = target.value

        if self._storage:
            asyncio.create_task(
                self._storage.update_workspace(
                    workspace_id,
                    runtime_state=target.value,
                )
            )

        return info

    def transition_workflow(self, workspace_id: str, target_state: str) -> WorkspaceInstance:
        """Transition workspace workflow state with validation.

        If storage is enabled, the state change is persisted.
        """
        info = self.get_workspace(workspace_id)
        current = WorkflowState(info.workflow_state)
        target = WorkflowState(target_state)
        if not validate_workflow_transition(current, target):
            raise InvalidTransitionError(current, target)
        info.workflow_state = target.value

        if self._storage:
            asyncio.create_task(
                self._storage.update_workspace(
                    workspace_id,
                    workflow_state=target.value,
                )
            )

        return info

    async def pause_workspace(self, workspace_id: str) -> None:
        """Pause workspace: shutdown agents, snapshot, suspend sandbox, persist."""
        info = self.get_workspace(workspace_id)
        async with self._ensure_lock(workspace_id):
            if info.runtime_state != RuntimeState.ACTIVE.value:
                raise InvalidTransitionError(RuntimeState(info.runtime_state), RuntimeState.PAUSED)
            await self._pause_workspace_locked(workspace_id, info)

    async def resume_workspace(self, workspace_id: str) -> None:
        """Resume paused workspace: reconnect sandbox, restart idle timer."""
        info = self.get_workspace(workspace_id)
        if not info.sandbox_conn:
            await self._connect_sandbox(workspace_id)
            return
        async with self._ensure_lock(workspace_id):
            if info.runtime_state != RuntimeState.PAUSED.value:
                raise InvalidTransitionError(RuntimeState(info.runtime_state), RuntimeState.ACTIVE)
            await self._resume_workspace_locked(workspace_id, info)

    async def destroy_workspace(self, workspace_id: str) -> None:
        """Destroy a workspace and kill its sandbox.

        If storage is enabled, the workspace is marked as failed (not deleted).
        """
        self._cancel_idle_timer(workspace_id)
        info = self.get_workspace(workspace_id)
        async with self._ensure_lock(workspace_id):
            if info.agent_manager:
                await info.agent_manager.shutdown_all()

            if info.sandbox_conn:
                await info.sandbox_conn.kill()

            info.runtime_state = RuntimeState.FAILED.value

        # Persist final state
        if self._storage:
            try:
                await self._storage.update_workspace(
                    workspace_id,
                    runtime_state=RuntimeState.FAILED.value,
                )
            except Exception as e:
                logger.error(f"Failed to persist destroyed workspace {workspace_id}: {e}")

        self._workspaces.pop(workspace_id, None)
        self._locks.pop(workspace_id, None)
        self._workspace_configs.pop(workspace_id, None)
        self._idle_timers.pop(workspace_id, None)
        self._active_turns.pop(workspace_id, None)

    def _start_idle_timer(self, workspace_id: str) -> None:
        """Start (or restart) the per-workspace idle countdown task."""
        self._cancel_idle_timer(workspace_id)
        self._idle_timers[workspace_id] = asyncio.create_task(self._idle_countdown(workspace_id))

    def _cancel_idle_timer(self, workspace_id: str) -> None:
        """Cancel the per-workspace idle task if running."""
        task = self._idle_timers.pop(workspace_id, None)
        if task and not task.done():
            task.cancel()

    async def _idle_countdown(self, workspace_id: str) -> None:
        """Sleep for pause_timeout seconds then auto-pause the workspace."""
        try:
            await asyncio.sleep(self._pause_timeout)
        except asyncio.CancelledError:
            return
        info = self._workspaces.get(workspace_id)
        if info and info.runtime_state == RuntimeState.ACTIVE.value:
            try:
                await self._pause_workspace(workspace_id)
            except Exception as e:
                logger.error(f"Auto-pause failed for {workspace_id}: {e}")

    async def _pause_workspace(self, workspace_id: str) -> None:
        """Pause workspace and create snapshot (acquires lock internally)."""
        self._cancel_idle_timer(workspace_id)
        info = self.get_workspace(workspace_id)
        if not info.sandbox_conn:
            return

        async with self._ensure_lock(workspace_id):
            await self._pause_workspace_locked(workspace_id, info)

    async def _pause_workspace_locked(self, workspace_id: str, info: WorkspaceInstance) -> None:
        """Pause workspace internals. Caller must hold self._locks[workspace_id]."""
        # Stop all agents (best-effort: don't let agent stop failure block pause)
        if info.agent_manager:
            try:
                await info.agent_manager.shutdown_all()
            except Exception as e:
                logger.warning(f"Agent shutdown failed for {workspace_id}: {e}")

        # Create snapshot (captures filesystem including ~/.claude/sessions/)
        try:
            snapshot_id = await info.sandbox_conn.create_snapshot()
        except Exception as e:
            logger.warning(f"Failed to create snapshot for {workspace_id}: {e}")
            snapshot_id = None

        # Pause sandbox
        provider_sandbox_id = await info.sandbox_conn.pause()

        info.provider_sandbox_id = provider_sandbox_id
        info.snapshot_id = snapshot_id
        info.runtime_state = RuntimeState.PAUSED.value

        # Persist
        if self._storage:
            await self._storage.update_workspace(
                workspace_id,
                provider_sandbox_id=provider_sandbox_id,
                snapshot_id=snapshot_id,
                runtime_state=RuntimeState.PAUSED.value,
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
        if not info.sandbox_conn or not info.provider_sandbox_id:
            raise ValueError("Cannot resume: sandbox or provider_sandbox_id is None")

        if TENACITY_AVAILABLE:
            # Use tenacity retry decorator
            @retry(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=1, min=2, max=10),
                retry=retry_if_exception_type((TimeoutException, ConnectException)),
            )
            async def _resume_with_retry() -> None:
                await info.sandbox_conn.resume(info.provider_sandbox_id)  # type: ignore

            await _resume_with_retry()
        else:
            # Fallback: simple retry without tenacity
            for attempt in range(3):
                try:
                    await info.sandbox_conn.resume(info.provider_sandbox_id)  # type: ignore
                    return
                except (TimeoutException, ConnectException) as e:
                    if attempt == 2:  # Last attempt
                        raise
                    logger.warning(f"Resume attempt {attempt + 1} failed: {e}, retrying...")
                    await asyncio.sleep(2**attempt)  # Exponential backoff

    async def _resume_workspace(self, workspace_id: str) -> None:
        """Resume paused workspace (acquires lock internally)."""
        info = self.get_workspace(workspace_id)
        if not info.sandbox_conn:
            await self._connect_sandbox(workspace_id)
            return
        async with self._ensure_lock(workspace_id):
            if info.runtime_state != RuntimeState.PAUSED.value:
                return
            await self._resume_workspace_locked(workspace_id, info)

    async def _resume_workspace_locked(self, workspace_id: str, info: "WorkspaceInstance") -> None:
        """Resume workspace internals. Caller must hold self._locks[workspace_id]."""
        try:
            await self._try_resume_sandbox(info)
        except (TimeoutException, ConnectException, SandboxDeadError) as e:
            if self._is_sandbox_expired(e) or isinstance(e, SandboxDeadError):
                await self._recover_from_snapshot(workspace_id, info, cause=e)
            else:
                raise

        info.runtime_state = RuntimeState.ACTIVE.value
        info.last_active = datetime.now(timezone.utc).isoformat()

        if self._storage:
            await self._storage.update_workspace(
                workspace_id,
                runtime_state=RuntimeState.ACTIVE.value,
                last_active=info.last_active,
                provider_sandbox_id=info.provider_sandbox_id,
            )

        if self._auto_pause:
            self._start_idle_timer(workspace_id)

        logger.info(f"Resumed workspace {workspace_id}")

    async def _recover_from_snapshot(
        self,
        workspace_id: str,
        info: WorkspaceInstance,
        cause: Exception,
    ) -> None:
        """Recover a failed/expired workspace from its stored snapshot.

        Creates a fresh E2B sandbox seeded from the snapshot, re-injects env
        vars and credentials (they are not persisted in snapshots), and updates
        the stored provider_sandbox_id.

        Raises ValueError if no snapshot is available or the snapshot itself
        is gone (provider returns "not found" for it).
        """
        if not info.snapshot_id:
            raise ValueError(
                f"Workspace {workspace_id} sandbox expired/killed and has no snapshot. "
                "Session is unrecoverable."
            ) from cause

        logger.warning(
            "Sandbox %s expired/killed, recovering from snapshot %s",
            info.provider_sandbox_id,
            info.snapshot_id,
        )

        if not info.sandbox_conn:
            raise ValueError(
                f"Workspace {workspace_id} has no live sandbox to recover into."
            ) from cause

        provider = info.sandbox_conn._provider

        # The provider must support snapshot-based creation (E2B-specific).
        # We check via duck-typing to stay compatible with custom providers.
        if not hasattr(provider, "create"):
            raise ValueError(
                f"Provider {type(provider).__name__} does not support snapshot recovery."
            ) from cause

        # Retrieve env vars from the sandbox config so we can re-inject them
        # (snapshots do not persist environment variables).
        config = self._workspace_configs.get(workspace_id)
        env_vars = dict(config.env_vars) if config and config.env_vars else {}
        sandbox_timeout = config.timeout if config else 300

        # Clear stale AgentProcess PIDs from the dead sandbox before creating the
        # replacement — matches what _pause_workspace already does.
        if info.agent_manager:
            await info.agent_manager.shutdown_all()

        try:
            # snapshot_id is an E2B-specific kwarg not on the base SandboxProvider
            # protocol — use Any cast to bypass structural typing here.
            await cast(Any, provider).create(
                env_vars=env_vars,
                timeout=sandbox_timeout,
                snapshot_id=info.snapshot_id,
            )
        except Exception as snap_err:
            snap_str = str(snap_err).lower()
            if any(p in snap_str for p in ("not found", "404", "does not exist")):
                raise ValueError(
                    f"Snapshot {info.snapshot_id} no longer exists. "
                    f"Workspace {workspace_id} is unrecoverable."
                ) from snap_err
            raise

        new_sandbox_id = provider.sandbox_id
        info.provider_sandbox_id = new_sandbox_id

        # Update storage with the new sandbox ID immediately so a crash
        # after create() but before the caller persists doesn't orphan the sandbox.
        if self._storage and new_sandbox_id:
            try:
                await self._storage.update_workspace(
                    workspace_id, provider_sandbox_id=new_sandbox_id
                )
            except Exception as e:
                logger.warning(
                    "Failed to persist new sandbox_id %s for workspace %s: %s",
                    new_sandbox_id,
                    workspace_id,
                    e,
                )

        logger.info(
            "Snapshot recovery successful: workspace %s running on new sandbox %s",
            workspace_id,
            new_sandbox_id,
        )

    async def shutdown_all(self) -> None:
        """Destroy all active workspaces and cancel per-workspace idle tasks."""
        # Cancel all idle countdown tasks
        for wid in list(self._idle_timers):
            self._cancel_idle_timer(wid)

        # Destroy all workspaces
        for wid in list(self._workspaces):
            try:
                await self.destroy_workspace(wid)
            except Exception:
                pass
