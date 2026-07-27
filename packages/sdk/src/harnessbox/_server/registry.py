"""Workspace registry — CRUD, lookup, pooling, and connection lifecycle.

Owns the in-memory registry of WorkspaceInstance objects, workspace creation,
hydration from storage, reconnection to expired/paused sandboxes, snapshot
recovery, and state transitions. Does NOT own prompt routing or idle timers.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from harnessbox._server.agent_manager import AgentManager
from harnessbox.lifecycle import (
    InvalidTransitionError,
    RuntimeState,
    validate_runtime_transition,
)
from harnessbox.providers import SandboxDeadError, SandboxProvider
from harnessbox.sandbox import Sandbox
from harnessbox.security.policy import SecurityPolicy
from harnessbox.streaming import EventType as StreamEventType
from harnessbox.streaming import UniversalEvent
from harnessbox.workspace import Workspace

if TYPE_CHECKING:
    from harnessbox._server.storage import StorageBackend

logger = logging.getLogger(__name__)

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

try:
    from e2b.exceptions import TimeoutException
    from e2b_connect.client import ConnectException
except ImportError:

    class TimeoutException(Exception):  # type: ignore[no-redef]
        pass

    class ConnectException(Exception):  # type: ignore[no-redef]
        pass


@dataclass
class WorkspaceConfig:
    """Reusable workspace configuration for WorkspaceRegistry.create_workspace()."""

    provider: str | SandboxProvider = "e2b"
    api_key: str | None = None
    harness: str = "claude-code"
    model: str | None = None
    system_prompt: str | Path | None = None
    security_policy: SecurityPolicy | None = None
    workspace: Workspace | None = None
    file_system: Any = None  # FileSystemSpec | None — avoid circular import at type level
    project_id: str | None = None
    env_vars: dict[str, str] = field(default_factory=dict)
    files: dict[str, str | Path] | list[str | Path] | None = None
    dirs: list[str] = field(default_factory=list)
    setup_script: str | None = None
    cwd: str | None = None
    timeout: int = 300
    skip_permissions: bool = False
    template: str | None = None
    session_timeout: int = 1800
    branch_label: str = ""
    remote_label: str = ""
    snapshot_id: str | None = None


@dataclass
class WorkspaceInstance:
    """Workspace record — in-memory state + persistent metadata."""

    workspace_id: str
    remote: str
    branch: str
    provider: str
    provider_sandbox_id: str | None
    snapshot_id: str | None
    runtime_state: str
    created_at: str
    last_active: str
    harness: str = "claude-code"

    sandbox_conn: Sandbox | None = None
    agent_manager: Any = None
    workspace_name: str | None = None
    base_branch: str | None = None
    total_cost_usd: float = 0.0
    error_message: str | None = None
    project_id: str | None = None
    file_system_path: str | None = None

    def to_record(self, config: WorkspaceConfig | None = None) -> dict[str, Any]:
        """Serialize to storage format (primitives only)."""
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
            "created_at": self.created_at,
            "last_active": self.last_active,
            "config_json": config_json,
            "workspace_name": self.workspace_name,
            "base_branch": self.base_branch,
            "total_cost_usd": self.total_cost_usd,
            "error_message": self.error_message,
        }


class WorkspaceNotFoundError(KeyError):
    """Raised when a workspace ID is not found in the registry."""


class WorkspaceRegistry:
    """Workspace CRUD, pooling, connection lifecycle, and state transitions.

    Thread-safe for use from a single asyncio event loop. Each workspace gets
    its own asyncio lock for serialized access to connection mutations.
    """

    def __init__(self, storage: StorageBackend | None = None) -> None:
        self._workspaces: dict[str, WorkspaceInstance] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._storage = storage
        self._workspace_configs: dict[str, WorkspaceConfig] = {}

    @property
    def storage(self) -> StorageBackend | None:
        return self._storage

    def _ensure_lock(self, workspace_id: str) -> asyncio.Lock:
        if workspace_id not in self._locks:
            self._locks[workspace_id] = asyncio.Lock()
        return self._locks[workspace_id]

    async def initialize(self) -> None:
        """Initialize storage and load persisted workspaces."""
        if self._storage:
            await self._storage.initialize()
            await self.load_workspaces()

    def register_workspace(
        self,
        config: WorkspaceConfig,
        *,
        workspace_id: str | None = None,
    ) -> WorkspaceInstance:
        """Register a workspace in STARTING state without provisioning the sandbox.

        Returns immediately so the HTTP layer can return 202. Call
        ``provision_workspace()`` to actually spin up the sandbox.
        """
        wid = workspace_id or str(uuid.uuid4())
        provider_name = config.provider if isinstance(config.provider, str) else "custom"

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

        info = WorkspaceInstance(
            workspace_id=wid,
            remote=remote,
            branch=branch,
            provider=provider_name,
            provider_sandbox_id=None,
            snapshot_id=None,
            runtime_state=RuntimeState.STARTING.value,
            created_at=datetime.now(timezone.utc).isoformat(),
            last_active=datetime.now(timezone.utc).isoformat(),
            harness=config.harness,
            workspace_name=workspace_name,
            base_branch=base_branch,
            project_id=config.project_id,
            file_system_path=(
                getattr(config.file_system, "mount_path", None) if config.file_system else None
            ),
        )

        self._workspaces[wid] = info
        self._locks[wid] = asyncio.Lock()
        self._workspace_configs[wid] = config

        return info

    async def provision_workspace(
        self,
        workspace_id: str,
        config: WorkspaceConfig,
        *,
        event_handler: Any = None,
    ) -> WorkspaceInstance:
        """Provision the sandbox for a registered workspace.

        On success, transitions to ACTIVE. On failure, transitions to ERROR
        with the error message stored on the instance.
        """
        info = self.get_workspace(workspace_id)

        try:
            sandbox = Sandbox(
                client=config.provider,
                api_key=config.api_key,
                harness=config.harness,
                model=config.model,
                system_prompt=config.system_prompt,
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
                session_timeout=0,
                snapshot_id=config.snapshot_id,
                file_system=config.file_system,
            )
            await sandbox.setup()

            agent_mgr = AgentManager(sandbox)
            info.sandbox_conn = sandbox
            info.agent_manager = agent_mgr
            info.provider_sandbox_id = sandbox.sandbox_id
            info.runtime_state = RuntimeState.ACTIVE.value
            info.last_active = datetime.now(timezone.utc).isoformat()

            await self._emit_runtime_state(workspace_id, RuntimeState.ACTIVE.value)

            if self._storage and isinstance(config.provider, str):
                try:
                    await self._storage.save_workspace(info.to_record(config))
                except Exception as e:
                    logger.error(f"Failed to persist workspace {workspace_id}: {e}")

        except Exception as exc:
            logger.exception("Failed to provision workspace %s", workspace_id)
            info.runtime_state = RuntimeState.ERROR.value
            info.error_message = str(exc)

            await self._emit_runtime_state(workspace_id, RuntimeState.ERROR.value)

            if self._storage:
                try:
                    await self._storage.update_workspace(
                        workspace_id,
                        runtime_state=RuntimeState.ERROR.value,
                    )
                except Exception as e:
                    logger.error(f"Failed to persist error state for {workspace_id}: {e}")

        return info

    def prepare_retry(self, workspace_id: str) -> WorkspaceConfig:
        """Validate and transition a workspace from ERROR back to STARTING for a retry.

        Returns the workspace's original config so the caller can re-run
        provision_workspace() (typically as a background task, mirroring the
        create-session 202 pattern). Raises InvalidTransitionError if the
        workspace isn't in ERROR, or ValueError if no stored config exists.
        """
        info = self.get_workspace(workspace_id)
        current = RuntimeState(info.runtime_state)
        target = RuntimeState.STARTING
        if not validate_runtime_transition(current, target):
            raise InvalidTransitionError(current, target)

        config = self._workspace_configs.get(workspace_id)
        if config is None:
            raise ValueError(f"No stored configuration for workspace {workspace_id}; cannot retry.")

        info.runtime_state = target.value
        info.error_message = None

        if self._storage:
            asyncio.create_task(
                self._storage.update_workspace(workspace_id, runtime_state=target.value)
            )

        return config

    async def create_workspace(
        self,
        config: WorkspaceConfig,
        *,
        workspace_id: str | None = None,
        event_handler: Any = None,
    ) -> WorkspaceInstance:
        """Create a new workspace with live sandbox (synchronous convenience method).

        Registers and provisions in one call. For async creation with 202 pattern,
        use ``register_workspace()`` + ``provision_workspace()`` separately.
        """
        info = self.register_workspace(config, workspace_id=workspace_id)
        await self.provision_workspace(info.workspace_id, config, event_handler=event_handler)
        return info

    def get_workspace(self, workspace_id: str) -> WorkspaceInstance:
        """Return workspace by ID or raise WorkspaceNotFoundError."""
        if workspace_id not in self._workspaces:
            raise WorkspaceNotFoundError(f"Workspace not found: {workspace_id}")
        return self._workspaces[workspace_id]

    def list_workspaces(self) -> list[WorkspaceInstance]:
        """List all workspaces currently in memory."""
        return list(self._workspaces.values())

    def find_by_repo_branch(self, remote: str, branch: str) -> WorkspaceInstance | None:
        """Find a workspace matching a repo remote URL and branch name."""
        for info in self._workspaces.values():
            if info.remote == remote and info.branch == branch:
                return info
        return None

    async def load_workspaces(self, limit: int = 100) -> None:
        """Load recent workspaces from storage into memory."""
        if not self._storage:
            return

        try:
            records = await self._storage.list_workspaces(limit=limit)
            for record in records:
                wid = record["workspace_id"]
                if wid in self._workspaces:
                    continue

                try:
                    _ = json.loads(record.get("config_json", "{}"))
                except json.JSONDecodeError:
                    logger.warning(f"Malformed config_json for workspace {wid}, skipping")
                    continue

                stored_state = record["runtime_state"]
                if stored_state == RuntimeState.ACTIVE.value:
                    stored_state = RuntimeState.PAUSED.value
                elif stored_state == RuntimeState.STARTING.value:
                    stored_state = RuntimeState.ERROR.value

                info = WorkspaceInstance(
                    workspace_id=wid,
                    remote=record.get("remote", ""),
                    branch=record.get("branch", ""),
                    provider=record["provider"],
                    provider_sandbox_id=record.get("provider_sandbox_id"),
                    snapshot_id=record.get("snapshot_id"),
                    runtime_state=stored_state,
                    created_at=record["created_at"],
                    last_active=record.get("last_active", record["created_at"]),
                    harness=record["harness"],
                    sandbox_conn=None,
                    agent_manager=None,
                    workspace_name=record.get("workspace_name"),
                    base_branch=record.get("base_branch"),
                    total_cost_usd=record.get("total_cost_usd", 0.0),
                    error_message=record.get("error_message"),
                )
                self._workspaces[wid] = info

            logger.info(f"Loaded {len(records)} workspaces from storage")
        except Exception as e:
            logger.error(f"Failed to load workspaces from storage: {e}")

    async def get_or_create_workspace(
        self,
        remote: str,
        branch: str,
        *,
        config: WorkspaceConfig | None = None,
        workspace_id: str | None = None,
    ) -> WorkspaceInstance:
        """Get existing paused workspace or create new one."""
        for info in self._workspaces.values():
            if (
                info.runtime_state == RuntimeState.PAUSED.value
                and info.remote == remote
                and info.branch == branch
            ):
                logger.info(
                    f"Pool hit: resuming workspace {info.workspace_id} for {remote}@{branch}"
                )
                await self.resume_workspace(info.workspace_id)
                return info

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
                info = self._hydrate_workspace(record)
                self._workspaces[wid] = info
                self._locks[wid] = asyncio.Lock()
                await self.resume_workspace(wid)
                return info

        if config is None:
            raise ValueError(
                f"No paused workspace found for {remote}@{branch} and config not provided."
            )

        logger.info(f"Pool miss: creating new workspace for {remote}@{branch}")
        return await self.create_workspace(config, workspace_id=workspace_id)

    def _hydrate_workspace(self, record: dict[str, Any]) -> WorkspaceInstance:
        """Recreate WorkspaceInstance from storage record (sandbox_conn=None)."""
        return WorkspaceInstance(
            workspace_id=record["workspace_id"],
            remote=record.get("remote", ""),
            branch=record.get("branch", ""),
            provider=record["provider"],
            provider_sandbox_id=record.get("provider_sandbox_id"),
            snapshot_id=record.get("snapshot_id"),
            runtime_state=record["runtime_state"],
            created_at=record["created_at"],
            last_active=record.get("last_active", record["created_at"]),
            harness=record["harness"],
            sandbox_conn=None,
            agent_manager=None,
            workspace_name=record.get("workspace_name"),
            base_branch=record.get("base_branch"),
            total_cost_usd=record.get("total_cost_usd", 0.0),
            error_message=record.get("error_message"),
        )

    # --- Connection lifecycle ---

    async def ensure_sandbox(self, workspace_id: str) -> None:
        """Ensure workspace has a live sandbox connection (lazy init)."""
        info = self.get_workspace(workspace_id)
        if info.sandbox_conn is None:
            await self._connect_sandbox(workspace_id)
        elif info.runtime_state == RuntimeState.PAUSED.value:
            await self.resume_workspace(workspace_id)

    async def _connect_sandbox(self, workspace_id: str) -> None:
        """Reconnect a workspace to its sandbox from stored configuration."""
        if not self._storage:
            raise ValueError(
                f"Workspace {workspace_id} has no live sandbox and no storage backend "
                "is configured — cannot reconnect without stored configuration."
            )

        async with self._ensure_lock(workspace_id):
            info = self.get_workspace(workspace_id)
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
                    f"Cannot reconnect workspace {workspace_id}: E2B API key not found."
                )

            initial_sequence = await self._storage.get_max_sequence(workspace_id)

            sandbox = Sandbox(
                client=record["provider"],
                api_key=api_key,
                harness=record["harness"],
                model=config_dict.get("model"),
                timeout=config_dict.get("timeout", 300),
                skip_permissions=config_dict.get("skip_permissions", False),
                template=config_dict.get("template"),
                session_timeout=0,
                initial_sequence=initial_sequence,
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
                                f"Workspace {workspace_id} sandbox expired and has no snapshot."
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
                    f"Workspace {workspace_id} has no provider_sandbox_id or snapshot_id."
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

        logger.info(f"Reconnected workspace {workspace_id}")

    # --- Pause / Resume / Destroy ---

    async def pause_workspace(self, workspace_id: str) -> None:
        """Pause workspace: snapshot, suspend sandbox, persist."""
        info = self.get_workspace(workspace_id)
        async with self._ensure_lock(workspace_id):
            if info.runtime_state != RuntimeState.ACTIVE.value:
                raise InvalidTransitionError(RuntimeState(info.runtime_state), RuntimeState.PAUSED)
            await self._pause_workspace_locked(workspace_id, info)

    async def resume_workspace(self, workspace_id: str) -> None:
        """Resume paused workspace: reconnect sandbox."""
        info = self.get_workspace(workspace_id)
        if not info.sandbox_conn:
            await self._connect_sandbox(workspace_id)
            return
        async with self._ensure_lock(workspace_id):
            if info.runtime_state != RuntimeState.PAUSED.value:
                raise InvalidTransitionError(RuntimeState(info.runtime_state), RuntimeState.ACTIVE)
            await self._resume_workspace_locked(workspace_id, info)

    async def destroy_workspace(self, workspace_id: str) -> None:
        """Destroy a workspace and kill its sandbox."""
        info = self.get_workspace(workspace_id)
        async with self._ensure_lock(workspace_id):
            if info.agent_manager:
                await info.agent_manager.shutdown_all()

            await self._emit_runtime_state(workspace_id, RuntimeState.DEAD.value)

            if info.sandbox_conn:
                await info.sandbox_conn.kill()

            info.runtime_state = RuntimeState.DEAD.value

        if self._storage:
            try:
                await self._storage.update_workspace(
                    workspace_id,
                    runtime_state=RuntimeState.DEAD.value,
                )
            except Exception as e:
                logger.error(f"Failed to persist destroyed workspace {workspace_id}: {e}")

        self._workspaces.pop(workspace_id, None)
        self._locks.pop(workspace_id, None)
        self._workspace_configs.pop(workspace_id, None)

    async def stop_workspace(self, workspace_id: str) -> None:
        """Kill a workspace's sandbox but keep its record queryable as DEAD.

        Unlike destroy_workspace, this does not remove the workspace from the
        registry — callers can still GET/list it afterwards. Safe to call on a
        workspace with no live sandbox (e.g. still STARTING, or already
        stopped) since sandbox_conn may be None.
        """
        info = self.get_workspace(workspace_id)
        async with self._ensure_lock(workspace_id):
            if info.agent_manager:
                await info.agent_manager.shutdown_all()

            await self._emit_runtime_state(workspace_id, RuntimeState.DEAD.value)

            if info.sandbox_conn:
                await info.sandbox_conn.kill()

            info.runtime_state = RuntimeState.DEAD.value

        if self._storage:
            try:
                await self._storage.update_workspace(
                    workspace_id,
                    runtime_state=RuntimeState.DEAD.value,
                )
            except Exception as e:
                logger.error(f"Failed to persist stopped workspace {workspace_id}: {e}")

    # --- Graceful shutdown ---

    async def graceful_shutdown(self) -> None:
        """Pause all active workspaces with snapshots for later recovery."""
        for wid in list(self._workspaces):
            info = self._workspaces[wid]
            if info.runtime_state != RuntimeState.ACTIVE.value:
                continue
            if info.sandbox_conn is None:
                continue
            try:
                async with self._ensure_lock(wid):
                    await asyncio.wait_for(
                        self._pause_workspace_locked(wid, info),
                        timeout=30.0,
                    )
                logger.info(f"Graceful shutdown: paused workspace {wid}")
            except asyncio.TimeoutError:
                logger.warning(f"Graceful shutdown: timeout pausing {wid}, skipping")
            except Exception as e:
                logger.warning(f"Graceful shutdown: failed to pause {wid}: {e}")

    async def shutdown_all(self) -> None:
        """Destroy all active workspaces."""
        for wid in list(self._workspaces):
            try:
                await self.destroy_workspace(wid)
            except Exception:
                pass

    # --- Internal helpers ---

    async def _pause_workspace_locked(self, workspace_id: str, info: WorkspaceInstance) -> None:
        """Pause workspace internals. Caller must hold the lock."""
        assert info.sandbox_conn is not None
        snapshot_id: str | None = None
        try:
            snapshot_id = await info.sandbox_conn.create_snapshot()
        except Exception as e:
            logger.warning(f"Failed to create snapshot for {workspace_id}: {e}")
            snapshot_id = info.snapshot_id

        await self._emit_runtime_state(workspace_id, RuntimeState.PAUSED.value)

        provider_sandbox_id = await info.sandbox_conn.pause()

        info.provider_sandbox_id = provider_sandbox_id
        info.snapshot_id = snapshot_id
        info.runtime_state = RuntimeState.PAUSED.value

        if self._storage:
            await self._storage.update_workspace(
                workspace_id,
                provider_sandbox_id=provider_sandbox_id,
                snapshot_id=snapshot_id,
                runtime_state=RuntimeState.PAUSED.value,
            )

        logger.info(f"Paused workspace {workspace_id}")

    async def _resume_workspace_locked(self, workspace_id: str, info: WorkspaceInstance) -> None:
        """Resume workspace internals. Caller must hold the lock."""
        try:
            await self._try_resume_sandbox(info)
        except (TimeoutException, ConnectException, SandboxDeadError) as e:
            if self._is_sandbox_expired(e) or isinstance(e, SandboxDeadError):
                await self._recover_from_snapshot(workspace_id, info, cause=e)
            else:
                raise
        else:
            # Sandbox reconnected in place (not recovered from snapshot). E2B
            # preserves the VM process, but Claude's outbound HTTP connection
            # can remain stale after pause/resume. A fresh process started with
            # the persisted Claude session ID is safer than reattaching stdout.
            if info.agent_manager:
                await info.agent_manager.shutdown_all()

        info.runtime_state = RuntimeState.ACTIVE.value
        info.last_active = datetime.now(timezone.utc).isoformat()

        await self._emit_runtime_state(workspace_id, RuntimeState.ACTIVE.value)

        if self._storage:
            await self._storage.update_workspace(
                workspace_id,
                runtime_state=RuntimeState.ACTIVE.value,
                last_active=info.last_active,
                provider_sandbox_id=info.provider_sandbox_id,
            )

        logger.info(f"Resumed workspace {workspace_id}")

    async def _try_resume_sandbox(self, info: WorkspaceInstance) -> None:
        """Attempt to resume sandbox with retries."""
        if not info.sandbox_conn or not info.provider_sandbox_id:
            raise ValueError("Cannot resume: sandbox or provider_sandbox_id is None")

        sandbox = info.sandbox_conn
        sandbox_id = info.provider_sandbox_id

        if TENACITY_AVAILABLE:

            @retry(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=1, min=2, max=10),
                retry=retry_if_exception_type((TimeoutException, ConnectException)),
            )
            async def _resume_with_retry() -> None:
                await sandbox.resume(sandbox_id)

            await _resume_with_retry()
        else:
            for attempt in range(3):
                try:
                    await sandbox.resume(sandbox_id)
                    return
                except (TimeoutException, ConnectException) as e:
                    if attempt == 2:
                        raise
                    logger.warning(f"Resume attempt {attempt + 1} failed: {e}, retrying...")
                    await asyncio.sleep(2**attempt)

    async def _recover_from_snapshot(
        self,
        workspace_id: str,
        info: WorkspaceInstance,
        cause: Exception,
    ) -> None:
        """Recover a failed/expired workspace from its stored snapshot."""
        if not info.snapshot_id:
            raise ValueError(
                f"Workspace {workspace_id} sandbox expired and has no snapshot."
            ) from cause

        logger.warning(
            "Sandbox %s expired, recovering from snapshot %s",
            info.provider_sandbox_id,
            info.snapshot_id,
        )

        if not info.sandbox_conn:
            raise ValueError(
                f"Workspace {workspace_id} has no live sandbox to recover into."
            ) from cause

        provider = info.sandbox_conn._provider

        if not hasattr(provider, "create"):
            raise ValueError(
                f"Provider {type(provider).__name__} does not support snapshot recovery."
            ) from cause

        config = self._workspace_configs.get(workspace_id)
        env_vars = dict(config.env_vars) if config and config.env_vars else {}
        sandbox_timeout = config.timeout if config else 300

        if info.agent_manager:
            await info.agent_manager.shutdown_all()

        try:
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
        if info.sandbox_conn:
            info.sandbox_conn._transition(RuntimeState.ACTIVE)

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

    async def _emit_runtime_state(self, workspace_id: str, state: str) -> None:
        """Emit a runtime.state event: broadcast live and persist durably.

        Must not silently no-op when there's no live sandbox yet — a workspace
        that fails STARTING -> ERROR before a Sandbox ever exists still needs
        that transition recorded, or reconnecting clients and /history never
        see it. When no buffer is available to assign a sequence, fall back to
        storage's max-sequence + 1 so retried failures don't collide on
        duplicate (workspace_id, 0) pairs, which storage silently drops.
        """
        info = self._workspaces.get(workspace_id)
        if not info:
            return

        buffer = info.sandbox_conn._event_buffer if info.sandbox_conn else None

        sequence = 0
        if not buffer and self._storage:
            try:
                sequence = await self._storage.get_max_sequence(workspace_id) + 1
            except Exception as e:
                logger.debug(f"Failed to look up sequence for {workspace_id}: {e}")

        event = UniversalEvent(
            event_id=str(uuid.uuid4()),
            sequence=sequence,
            timestamp=datetime.now(timezone.utc).isoformat(),
            session_id=workspace_id,
            event_type=StreamEventType.RUNTIME_STATE,
            metadata={"runtime_state": state},
        )

        if buffer:
            try:
                event = await buffer.push(event)
            except Exception as e:
                logger.debug(f"Failed to broadcast runtime state event for {workspace_id}: {e}")

        if self._storage:
            try:
                await self._storage.append_events(workspace_id, [event.to_storage_dict()])
            except Exception as e:
                logger.debug(f"Failed to persist runtime state event for {workspace_id}: {e}")

    @staticmethod
    def _create_from_snapshot(
        sandbox: Sandbox,
        config_dict: dict[str, Any],
        snapshot_id: str,
        *,
        env_vars: dict[str, str] | None = None,
    ) -> Any:
        """Create a sandbox from a snapshot and transition to ACTIVE state."""

        async def _do_create() -> None:
            resolved_vars = env_vars if env_vars is not None else config_dict.get("env_vars", {})
            timeout = config_dict.get("timeout", 300)
            await cast(Any, sandbox._provider).create(
                env_vars=resolved_vars,
                timeout=timeout,
                snapshot_id=snapshot_id,
            )
            sandbox._transition(RuntimeState.ACTIVE)

        return _do_create()

    @staticmethod
    def _is_sandbox_expired(error: Exception) -> bool:
        """Detect if error indicates sandbox no longer exists."""
        error_str = str(error).lower()
        return any(
            pattern in error_str
            for pattern in ["sandbox was not found", "404", "not found", "does not exist"]
        )

    @staticmethod
    def _resolve_provider_api_key(provider: str) -> str | None:
        """Resolve provider API key from environment or config files."""
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
                    for f in ("teamApiKey", "accessToken"):
                        val = (data.get(f) or "").strip()
                        if val:
                            return val
            except Exception:
                pass

        return None

    @staticmethod
    def _resolve_env_vars(key_names: list[str]) -> dict[str, str]:
        """Resolve environment variable values from the host by key name."""
        import os

        resolved: dict[str, str] = {}
        for key in key_names:
            val = os.environ.get(key, "").strip()
            if val:
                resolved[key] = val
        return resolved
