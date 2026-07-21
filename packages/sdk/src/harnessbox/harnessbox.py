"""HarnessBox — public API wrapper for sandbox orchestration."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Coroutine, Literal, overload

from harnessbox.lifecycle import RuntimeState
from harnessbox.providers import CommandResult, SandboxProvider
from harnessbox.sandbox import Sandbox
from harnessbox.security.policy import SecurityPolicy
from harnessbox.streaming import UniversalEvent
from harnessbox.types import AgentResponse
from harnessbox.workspace import GitRepoConfig

_log = logging.getLogger("harnessbox.api")


@dataclass(frozen=True)
class Snapshot:
    """A saved sandbox snapshot that can be used to fork new sandboxes."""

    id: str


@dataclass(frozen=True)
class WorkspaceConfig:
    """Structured workspace configuration for HarnessBox."""

    git_repo_config: GitRepoConfig | None = None


class Session:
    """Handle to a running agent session.

    Returned by ``HarnessBox.create_session()``. Each Session wraps a single
    Sandbox instance.
    """

    def __init__(self, session_id: str, branch: str, sandbox: Sandbox) -> None:
        self._session_id = session_id
        self._branch = branch
        self._sandbox = sandbox

    @property
    def id(self) -> str:
        """Unique session identifier."""
        return self._session_id

    @property
    def branch(self) -> str:
        """Git branch this session operates on."""
        return self._branch

    @property
    def sandbox(self) -> Sandbox:
        """Underlying Sandbox instance."""
        return self._sandbox

    @property
    def sandbox_id(self) -> str | None:
        """Provider sandbox ID for this session."""
        return self._sandbox.sandbox_id

    @property
    def status(self) -> RuntimeState:
        """Current workspace/sandbox lifecycle state."""
        return self._sandbox.state

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
            return self._sandbox.send_message(input, stream=True)
        return self._sandbox.send_message(input, stream=False)

    async def run_command(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int | None = None,
    ) -> CommandResult:
        """Run a shell command in this session's sandbox."""
        return await self._sandbox.run_command(command, cwd=cwd, timeout=timeout)

    async def kill(self) -> None:
        """Destroy this session's sandbox and release resources."""
        await self._sandbox.kill()


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
        env_vars: dict[str, str] | None = None,
        files: dict[str, str | Path] | list[str | Path] | None = None,
        setup_script: str | None = None,
        security_policy: SecurityPolicy | None = None,
        timeout: int = 300,
        template: str | None = None,
        cwd: str | None = None,
        workspace_config: WorkspaceConfig | None = None,
    ) -> None:
        self._provider = provider
        self._harness = harness
        self._api_key = api_key
        self._model = model
        self._system_prompt = system_prompt
        self._env_vars = dict(env_vars) if env_vars else {}
        self._files = files
        self._setup_script = setup_script
        self._security_policy = security_policy
        self._timeout = timeout
        self._template = template
        self._cwd = cwd
        self._workspace_config = workspace_config
        self._secrets = self._resolve_secrets(secrets)
        self._snapshot_id: str | None = None
        self._sessions: dict[str, Session] = {}

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
        resolved_branch = branch
        if resolved_branch is None:
            if self._workspace_config and self._workspace_config.git_repo_config:
                resolved_branch = self._workspace_config.git_repo_config.branch or "main"
            else:
                resolved_branch = "main"

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
                branch=resolved_branch,
                base_branch=src.base_branch,
                auth_token=git_token,
            )

        sandbox = Sandbox(
            client=self._provider,
            api_key=self._secrets.provider_api_key,
            harness=self._harness,
            model=self._model,
            system_prompt=self._system_prompt,
            security_policy=self._security_policy,
            workspace=workspace,
            env_vars=merged_env or None,
            files=self._files,
            setup_script=self._setup_script,
            cwd=self._cwd,
            timeout=self._timeout,
            template=self._template,
            skip_permissions=True,
            snapshot_id=self._snapshot_id,
        )
        await sandbox.setup()

        session_id = str(uuid.uuid4())
        session = Session(session_id=session_id, branch=resolved_branch, sandbox=sandbox)
        self._sessions[session_id] = session
        return session

    async def save_snapshot(self, session: Session | None = None) -> Snapshot:
        """Save a snapshot of a session's sandbox filesystem state.

        The sandbox pauses briefly during the snapshot and returns to running
        state. Use the returned Snapshot to fork new sandboxes via
        ``create_from_snapshot()``.

        Args:
            session: Session to snapshot. If omitted, snapshots the most
                recently created active session.
        """
        if session is not None:
            target = session
        else:
            active = [s for s in self._sessions.values() if s.sandbox.state == RuntimeState.ACTIVE]
            if not active:
                raise RuntimeError("No active sessions — nothing to snapshot.")
            target = active[-1]

        snapshot_id = await target.sandbox.create_snapshot()
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
        for session in list(self._sessions.values()):
            await session.kill()
        self._sessions.clear()

    async def __aenter__(self) -> HarnessBox:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        await self.kill()
