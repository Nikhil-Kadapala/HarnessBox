"""HarnessBox — public API wrapper for sandbox orchestration."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Coroutine, Literal, overload

from harnessbox.lifecycle import RuntimeState, SessionStatus, to_session_status
from harnessbox.providers import CommandResult, SandboxProvider
from harnessbox.security.policy import SecurityPolicy
from harnessbox.streaming import UniversalEvent
from harnessbox.types import AgentResponse
from harnessbox.workspace import GitRepoConfig

if TYPE_CHECKING:
    from harnessbox.storage import StorageBackend
    from harnessbox.workspace_manager import WorkspaceManager

_log = logging.getLogger("harnessbox.api")


class WorkspaceMode(str, Enum):
    """How sessions map to sandboxes."""

    NEW = "new"
    SHARED = "shared"


@dataclass(frozen=True)
class Snapshot:
    """A saved sandbox snapshot that can be used to fork new sandboxes."""

    id: str


@dataclass(frozen=True)
class FileSystemConfig:
    """Placeholder for future filesystem workspace configuration."""

    pass


@dataclass(frozen=True)
class WorkspaceConfig:
    """Structured workspace configuration for HarnessBox."""

    workspace_mode: WorkspaceMode = WorkspaceMode.NEW
    git_repo_config: GitRepoConfig | None = None
    file_system_config: FileSystemConfig | None = None


class Session:
    """Handle to a running agent session.

    Returned by ``HarnessBox.create_session()``. Each Session corresponds to one
    workspace in the internal WorkspaceManager.
    """

    def __init__(
        self,
        session_id: str,
        branch: str,
        manager: WorkspaceManager,
    ) -> None:
        self._session_id = session_id
        self._branch = branch
        self._manager = manager

    @property
    def id(self) -> str:
        """Unique session identifier."""
        return self._session_id

    @property
    def branch(self) -> str:
        """Git branch this session operates on."""
        return self._branch

    @property
    def sandbox_id(self) -> str | None:
        """Provider sandbox ID for this session."""
        from harnessbox.workspace_manager import WorkspaceNotFoundError

        try:
            info = self._manager.get_workspace(self._session_id)
        except WorkspaceNotFoundError:
            return None
        return info.provider_sandbox_id

    @property
    def status(self) -> SessionStatus:
        """User-facing session status: running, sleeping, or killed."""
        from harnessbox.workspace_manager import WorkspaceNotFoundError

        try:
            info = self._manager.get_workspace(self._session_id)
        except WorkspaceNotFoundError:
            return SessionStatus.KILLED
        return to_session_status(RuntimeState(info.runtime_state))

    @overload
    def send_message(
        self, input: str, *, stream: Literal[True] = True
    ) -> AsyncGenerator[UniversalEvent, None]: ...

    @overload
    def send_message(
        self, input: str, *, stream: Literal[False]
    ) -> Coroutine[Any, Any, AgentResponse]: ...

    def send_message(
        self, input: str, *, stream: bool = True
    ) -> AsyncGenerator[UniversalEvent, None] | Coroutine[Any, Any, AgentResponse]:
        """Send a message to the agent in this session."""
        if stream:
            return self._manager.prompt(self._session_id, input)
        return self._collect_response(input)

    async def _collect_response(self, input: str) -> AgentResponse:
        events: list[UniversalEvent] = []
        text_parts: list[str] = []
        cost_usd: float | None = None
        duration_ms: int | None = None
        session_id = ""

        async for event in self._manager.prompt(self._session_id, input):
            events.append(event)
            if event.delta and event.item_kind == "message":
                text_parts.append(event.delta)
            if event.session_id:
                session_id = event.session_id
            if event.cost_usd is not None:
                cost_usd = event.cost_usd
            if event.duration_ms is not None:
                duration_ms = event.duration_ms

        return AgentResponse(
            text="".join(text_parts),
            cost_usd=cost_usd,
            duration_ms=duration_ms,
            session_id=session_id,
            events=events,
        )

    async def run_command(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int | None = None,
    ) -> CommandResult:
        """Run a shell command in this session's sandbox."""
        info = self._manager.get_workspace(self._session_id)
        if info.sandbox_conn is None:
            raise RuntimeError(f"Session {self._session_id} has no live sandbox connection")
        return await info.sandbox_conn.run_command(command, cwd=cwd, timeout=timeout)

    async def kill(self) -> None:
        """Destroy this session's sandbox and release resources."""
        from harnessbox.workspace_manager import WorkspaceNotFoundError

        try:
            await self._manager.destroy_workspace(self._session_id)
        except WorkspaceNotFoundError:
            pass


@dataclass(frozen=True)
class HarnessBoxSecrets:
    """Structured secrets for sandbox provisioning."""

    provider_api_key: str | None = None
    harness_secrets: dict[str, str] | None = None


class HarnessBox:
    """Public API for running AI coding agents in secure sandboxes.

    Example::

        from harnessbox import HarnessBox, WorkspaceConfig
        from harnessbox.workspace import GitRepoConfig

        hb = HarnessBox(
            provider="e2b",
            harness="claude-code",
            workspace_config=WorkspaceConfig(
                git_repo_config=GitRepoConfig(
                    remote="https://github.com/org/repo.git",
                    branch="feat/auth",
                    base_branch="main",
                ),
            ),
            secrets=HarnessBoxSecrets(
                provider_api_key=os.getenv("E2B_API_KEY"),
                harness_secrets={"ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY")},
            ),
        )

        session = await hb.create_session()
        async for event in session.send_message("Fix the failing test"):
            print(event.delta or "", end="")
        await session.kill()
    """

    def __init__(
        self,
        *,
        provider: SandboxProvider | str = "e2b",
        harness: str = "claude-code",
        api_key: str | None = None,
        secrets: dict[str, Any] | HarnessBoxSecrets | None = None,
        model: str | None = None,
        system_prompt: str | Path | None = None,
        skills: list[str | Path] | None = None,
        plugins: list[str | Path] | None = None,
        env_vars: dict[str, str] | None = None,
        files: dict[str, str | Path] | list[str | Path] | None = None,
        setup_script: str | None = None,
        security_policy: SecurityPolicy | None = None,
        timeout: int = 300,
        template: str | None = None,
        cwd: str | None = None,
        workspace_config: WorkspaceConfig | None = None,
        storage: StorageBackend | None = None,
    ) -> None:
        self._provider = provider
        self._harness = harness
        self._api_key = api_key
        self._model = model
        self._system_prompt = system_prompt
        self._skills = skills
        self._plugins = plugins
        self._env_vars = dict(env_vars) if env_vars else {}
        self._files = files
        self._setup_script = setup_script
        self._security_policy = security_policy
        self._timeout = timeout
        self._template = template
        self._cwd = cwd
        self._workspace_config = workspace_config
        self._storage = storage

        self._secrets = self._resolve_secrets(secrets)

        self._snapshot_id: str | None = None
        self._manager: WorkspaceManager | None = None
        self._initialized = False
        if workspace_config is not None:
            from harnessbox.workspace_manager import WorkspaceManager as WM

            self._manager = WM(storage=storage)

    @staticmethod
    def _resolve_secrets(
        secrets: dict[str, Any] | HarnessBoxSecrets | None,
    ) -> HarnessBoxSecrets:
        if secrets is None:
            return HarnessBoxSecrets()
        if isinstance(secrets, HarnessBoxSecrets):
            return secrets
        return HarnessBoxSecrets(
            provider_api_key=secrets.get("provider_api_key"),
            harness_secrets=secrets.get("harness_secrets"),
        )

    async def create_session(self, branch: str | None = None) -> Session:
        """Create a new session.

        Each call provisions a new sandbox. When ``git_repo_config`` is set in
        the workspace config, the sandbox clones the repo and checks out the
        given branch.

        Args:
            branch: Git branch for this session. Overrides the default from
                ``workspace_config.git_repo_config.branch``. Falls back to
                "main" if neither is specified.

        Returns:
            A Session handle for interacting with the agent.
        """
        if self._manager is None:
            raise RuntimeError(
                "create_session() requires workspace_config. "
                "Pass workspace_config=WorkspaceConfig() to HarnessBox()."
            )
        if self._workspace_config is not None and (
            self._workspace_config.workspace_mode == WorkspaceMode.SHARED
        ):
            raise NotImplementedError(
                "WorkspaceMode.SHARED is not yet implemented. Use WorkspaceMode.NEW."
            )

        if not self._initialized and self._storage is not None:
            await self._storage.initialize()
            await self._manager.load_workspaces()
            self._initialized = True

        resolved_branch = branch
        if resolved_branch is None:
            if self._workspace_config and self._workspace_config.git_repo_config:
                resolved_branch = self._workspace_config.git_repo_config.branch or "main"
            else:
                resolved_branch = "main"

        config = self._build_workspace_config(resolved_branch)
        info = await self._manager.create_workspace(config)
        return Session(
            session_id=info.workspace_id,
            branch=resolved_branch,
            manager=self._manager,
        )

    def _build_workspace_config(self, branch: str) -> Any:
        """Convert HarnessBox init params into internal WorkspaceConfig."""
        from harnessbox.workspace_manager import WorkspaceConfig as InternalWorkspaceConfig

        merged_env = dict(self._env_vars)
        if self._secrets.harness_secrets:
            merged_env.update(self._secrets.harness_secrets)

        workspace = None
        if self._workspace_config and self._workspace_config.git_repo_config:
            src = self._workspace_config.git_repo_config
            git_token = (
                src._auth_token or merged_env.get("GITHUB_TOKEN") or merged_env.get("GIT_TOKEN")
            )
            workspace = GitRepoConfig(
                remote=src.remote,
                branch=branch,
                base_branch=src.base_branch,
                auth_token=git_token,
            )

        remote_label = ""
        if self._workspace_config and self._workspace_config.git_repo_config:
            remote_label = self._workspace_config.git_repo_config.remote

        return InternalWorkspaceConfig(
            provider=self._provider,
            api_key=self._secrets.provider_api_key,
            harness=self._harness,
            model=self._model,
            system_prompt=self._system_prompt,
            skills=self._skills or [],
            plugins=self._plugins or [],
            security_policy=self._security_policy,
            workspace=workspace,
            env_vars=merged_env,
            files=self._files,
            setup_script=self._setup_script,
            cwd=self._cwd,
            timeout=self._timeout,
            template=self._template,
            skip_permissions=True,
            branch_label=branch,
            remote_label=remote_label,
            snapshot_id=getattr(self, "_snapshot_id", None),
        )

    async def save_snapshot(self, session: Session | None = None) -> Snapshot:
        """Save a snapshot of a session's sandbox filesystem state.

        The sandbox pauses briefly during the snapshot and returns to running
        state. Use the returned Snapshot to fork new sandboxes via
        ``create_from_snapshot()``.

        Args:
            session: Session to snapshot. If omitted, snapshots the most
                recently created active session.
        """
        if self._manager is None:
            raise RuntimeError("save_snapshot() requires an active session.")

        if session is not None:
            info = self._manager.get_workspace(session.id)
        else:
            workspaces = self._manager.list_workspaces()
            active = [
                w
                for w in workspaces
                if w.sandbox_conn is not None and w.runtime_state == RuntimeState.ACTIVE.value
            ]
            if not active:
                raise RuntimeError("No active sessions — nothing to snapshot.")
            info = active[-1]

        if info.sandbox_conn is None:
            raise RuntimeError(f"Session {info.workspace_id} has no live sandbox connection.")

        snapshot_id = await info.sandbox_conn.create_snapshot()
        return Snapshot(id=snapshot_id)

    @classmethod
    def create_from_snapshot(
        cls,
        snapshot_id: str,
        *,
        api_key: str | None = None,
        harness: str = "claude-code",
    ) -> HarnessBox:
        """Create a HarnessBox that will fork from a previously saved snapshot.

        The new sandbox starts with the snapshot's filesystem state. Running
        processes do not carry over — call ``create_session()`` to launch an
        agent in the forked sandbox.
        """
        hb = cls(
            provider="e2b",
            harness=harness,
            api_key=api_key,
            workspace_config=WorkspaceConfig(),
        )
        hb._snapshot_id = snapshot_id
        return hb

    async def kill(self) -> None:
        """Destroy all sessions and release resources."""
        if self._manager is not None:
            await self._manager.shutdown_all()

    async def __aenter__(self) -> HarnessBox:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        await self.kill()
