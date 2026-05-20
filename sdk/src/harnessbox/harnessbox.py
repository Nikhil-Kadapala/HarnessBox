"""HarnessBox — public API wrapper for sandbox orchestration."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Coroutine, Literal, overload

from harnessbox.providers import CommandResult, SandboxProvider
from harnessbox.sandbox import InteractiveSession, Sandbox
from harnessbox.security.policy import SecurityPolicy
from harnessbox.streaming import UniversalEvent
from harnessbox.types import AgentResponse
from harnessbox.workspace import Workspace

if TYPE_CHECKING:
    from harnessbox.storage import StorageBackend
    from harnessbox.workspace_manager import WorkspaceManager

_log = logging.getLogger("harnessbox.api")


class WorkspaceMode(str, Enum):
    """How sessions map to sandboxes."""

    NEW = "new"
    SHARED = "shared"


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
    def status(self) -> str:
        """Current session state (synchronous dict lookup)."""
        from harnessbox.workspace_manager import WorkspaceNotFoundError

        try:
            info = self._manager.get_workspace(self._session_id)
        except WorkspaceNotFoundError:
            return "ended"
        return info.status

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
        if info.sandbox is None:
            raise RuntimeError(f"Session {self._session_id} has no live sandbox")
        return await info.sandbox.run_command(command, cwd=cwd, timeout=timeout)

    async def kill(self) -> None:
        """Destroy this session's sandbox and release resources."""
        from harnessbox.workspace_manager import WorkspaceNotFoundError

        try:
            await self._manager.destroy_workspace(self._session_id)
        except WorkspaceNotFoundError:
            pass


@dataclass(frozen=True)
class HarnessBoxSecrets:
    """Structured secrets for sandbox provisioning.

    Separates provider credentials from harness (agent) credentials.
    """

    provider_api_key: str | None = None
    harness_secrets: dict[str, str] | None = None


class HarnessBox:
    """Public API for running AI coding agents in secure sandboxes.

    Wraps the internal Sandbox orchestration with a clean interface
    that separates platform auth, provider credentials, and agent secrets.

    Example::

        import os
        from harnessbox import HarnessBox

        hb = HarnessBox(
            provider="e2b",
            harness="claude-code",
            secrets={
                "provider_api_key": os.getenv("E2B_API_KEY"),
                "harness_secrets": {
                    "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY"),
                },
            },
        )

        sandbox_id = await hb.create()
        async for event in hb.send_message("Fix the failing test"):
            print(event.delta or "", end="")
        await hb.kill()
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
        workspace: Workspace | None = None,
        setup_script: str | None = None,
        security_policy: SecurityPolicy | None = None,
        timeout: int = 300,
        template: str | None = None,
        cwd: str | None = None,
        remote: str | None = None,
        workspace_mode: WorkspaceMode | None = None,
        storage: StorageBackend | None = None,
    ) -> None:
        """Create a HarnessBox instance.

        Args:
            provider: Sandbox provider — a name (``"e2b"``, ``"daytona"``)
                or a ``SandboxProvider`` instance.
            harness: Agent harness type (``"claude-code"``, ``"codex"``).
            api_key: HarnessBox platform API key. Required for paid
                features. Use ``"hb_self_hosted"`` for self-hosted mode.
            secrets: Provider and agent credentials. Accepts a dict with
                ``provider_api_key`` and ``harness_secrets`` keys, or a
                ``HarnessBoxSecrets`` instance.
            model: Override the default model for the harness.
            system_prompt: Agent system prompt (str content or Path to file).
            skills: Skill files/dirs to inject into the sandbox.
            plugins: Plugin directories to inject.
            env_vars: Additional environment variables for the sandbox.
            files: Files to inject into the sandbox.
            workspace: Git workspace to clone (single-session mode).
            setup_script: Shell command to run after setup.
            security_policy: Security deny rules and credential guards.
            timeout: Sandbox creation timeout in seconds.
            template: Override the provider sandbox template.
            cwd: Working directory for agent commands.
            remote: Git remote URL for multi-session mode.
            workspace_mode: Enable multi-session mode (``WorkspaceMode.NEW``).
            storage: Persistence backend for multi-session workspaces.
        """
        self._provider = provider
        self._harness = harness
        self._api_key = api_key
        self._model = model
        self._system_prompt = system_prompt
        self._skills = skills
        self._plugins = plugins
        self._env_vars = dict(env_vars) if env_vars else {}
        self._files = files
        self._workspace = workspace
        self._setup_script = setup_script
        self._security_policy = security_policy
        self._timeout = timeout
        self._template = template
        self._cwd = cwd
        self._remote = remote
        self._workspace_mode = workspace_mode
        self._storage = storage

        # Resolve secrets
        self._secrets = self._resolve_secrets(secrets)

        # Multi-session mode: create WorkspaceManager lazily
        self._manager: WorkspaceManager | None = None
        self._initialized = False
        if workspace_mode is not None:
            from harnessbox.workspace_manager import WorkspaceManager as WM

            self._manager = WM(storage=storage)

        # Internal sandbox — created lazily in create() (single-session mode)
        self._sandbox: Sandbox | None = None

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

    async def create_session(self, branch: str = "main") -> Session:
        """Create a new session (multi-session mode only).

        Each call provisions a new sandbox. When ``remote`` is configured,
        the sandbox clones the repo and checks out the given branch. Without
        ``remote``, the branch is used only as a metadata label.

        Args:
            branch: Git branch for this session's workspace. Only triggers
                a clone/checkout if ``remote`` was set at init.

        Returns:
            A Session handle for interacting with the agent.

        Raises:
            RuntimeError: If workspace_mode was not set at init.
            NotImplementedError: If workspace_mode is SHARED.
        """
        if self._manager is None:
            raise RuntimeError(
                "create_session() requires workspace_mode. "
                "Pass workspace_mode=WorkspaceMode.NEW to HarnessBox()."
            )
        if self._workspace_mode == WorkspaceMode.SHARED:
            raise NotImplementedError(
                "WorkspaceMode.SHARED is not yet implemented. Use WorkspaceMode.NEW."
            )

        if not self._initialized and self._storage is not None:
            await self._storage.initialize()
            await self._manager.load_workspaces()
            self._initialized = True

        config = self._build_workspace_config(branch)
        info = await self._manager.create_workspace(config)
        return Session(
            session_id=info.workspace_id,
            branch=branch,
            manager=self._manager,
        )

    def _build_workspace_config(self, branch: str) -> Any:
        """Convert HarnessBox init params into internal WorkspaceConfig."""
        from harnessbox.workspace import GitWorkspace
        from harnessbox.workspace_manager import WorkspaceConfig

        merged_env = dict(self._env_vars)
        if self._secrets.harness_secrets:
            merged_env.update(self._secrets.harness_secrets)

        workspace = None
        if self._remote:
            git_token = merged_env.get("GITHUB_TOKEN") or merged_env.get("GIT_TOKEN")
            workspace = GitWorkspace(
                remote=self._remote,
                branch=branch,
                base_branch="main",
                auth_token=git_token,
            )

        return WorkspaceConfig(
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
        )

    @property
    def is_self_hosted(self) -> bool:
        """True if running without a platform API key (self-hosted mode)."""
        return self._api_key is None or self._api_key.startswith("hb_self_hosted")

    @property
    def sandbox_id(self) -> str | None:
        """Return the provider sandbox ID, or None if not yet created."""
        if self._sandbox is None:
            return None
        return self._sandbox.sandbox_id

    @property
    def sandbox(self) -> Sandbox | None:
        """Return the underlying Sandbox instance (internal use)."""
        return self._sandbox

    async def create(self) -> str:
        """Provision the sandbox and inject all configuration.

        Permission prompts are disabled (``skip_permissions=True``) because
        HarnessBox targets headless/programmatic use where sandboxes are
        isolated. For interactive sessions requiring permission prompts, use
        the lower-level ``Sandbox`` class directly.

        Returns:
            The provider sandbox ID.

        Raises:
            RuntimeError: If create() has already been called or if the
                provider fails to assign a sandbox ID.
        """
        if self._sandbox is not None:
            raise RuntimeError("HarnessBox already created. Call kill() before re-creating.")

        # Merge harness secrets into env_vars for sandbox injection
        merged_env = dict(self._env_vars)
        if self._secrets.harness_secrets:
            merged_env.update(self._secrets.harness_secrets)

        self._sandbox = Sandbox(
            client=self._provider,
            api_key=self._secrets.provider_api_key,
            harness=self._harness,
            model=self._model,
            system_prompt=self._system_prompt,
            skills=self._skills,
            plugins=self._plugins,
            env_vars=merged_env or None,
            files=self._files,
            workspace=self._workspace,
            setup_script=self._setup_script,
            security_policy=self._security_policy,
            timeout=self._timeout,
            template=self._template,
            cwd=self._cwd,
            skip_permissions=True,
        )

        await self._sandbox.setup()
        sandbox_id = self._sandbox.sandbox_id
        if not sandbox_id:
            raise RuntimeError(
                "Sandbox setup completed but no sandbox_id was assigned by provider."
            )
        _log.info("HarnessBox created: %s", sandbox_id)
        return sandbox_id

    def _require_sandbox(self) -> Sandbox:
        if self._sandbox is None:
            raise RuntimeError("HarnessBox not created. Call 'await hb.create()' first.")
        return self._sandbox

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
        """Send a message to the agent.

        Args:
            input: The user message.
            stream: If True (default), returns an async generator of events.
                If False, returns an awaitable AgentResponse.
        """
        sb = self._require_sandbox()
        if not stream:
            return sb.send_message(input, stream=False)
        return sb.send_message(input, stream=True)

    async def run_command(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int | None = None,
    ) -> CommandResult:
        """Run a shell command inside the sandbox."""
        sb = self._require_sandbox()
        return await sb.run_command(command, cwd=cwd, timeout=timeout)

    async def write_file(self, path: str, content: str) -> None:
        """Write a file inside the sandbox."""
        sb = self._require_sandbox()
        await sb.write_file(path, content)

    async def write_files(self, files: dict[str, str]) -> None:
        """Write multiple files inside the sandbox."""
        sb = self._require_sandbox()
        await sb.write_files(files)

    async def read_file(self, path: str) -> str:
        """Read a file from the sandbox."""
        sb = self._require_sandbox()
        return await sb.read_file(path)

    async def start_interactive_session(self) -> InteractiveSession:
        """Start a live PTY session with the agent."""
        sb = self._require_sandbox()
        return await sb.start_interactive_session()

    async def kill(self) -> None:
        """Destroy sandbox(es) and release resources.

        In multi-session mode, shuts down all sessions. In single-session
        mode, destroys the single sandbox. Closes storage if owned.
        """
        if self._manager is not None:
            await self._manager.shutdown_all()
        if self._sandbox is not None:
            try:
                await self._sandbox.kill()
            finally:
                self._sandbox = None
        if self._storage is not None:
            await self._storage.close()

    async def __aenter__(self) -> HarnessBox:
        await self.create()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        await self.kill()
