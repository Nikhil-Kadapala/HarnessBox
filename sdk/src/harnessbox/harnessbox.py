"""HarnessBox — public API wrapper for sandbox orchestration."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Coroutine, Literal, overload

from harnessbox.providers import CommandResult, SandboxProvider
from harnessbox.sandbox import InteractiveSession, Sandbox
from harnessbox.security.policy import SecurityPolicy
from harnessbox.streaming import UniversalEvent
from harnessbox.types import AgentResponse
from harnessbox.workspace import Workspace

_log = logging.getLogger("harnessbox.api")


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
            workspace: Git workspace to clone.
            setup_script: Shell command to run after setup.
            security_policy: Security deny rules and credential guards.
            timeout: Sandbox creation timeout in seconds.
            template: Override the provider sandbox template.
            cwd: Working directory for agent commands.
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

        # Resolve secrets
        self._secrets = self._resolve_secrets(secrets)

        # Internal sandbox — created lazily in create()
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
            raise RuntimeError("Sandbox setup completed but no sandbox_id was assigned by provider.")
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
        """Destroy the sandbox and release resources."""
        if self._sandbox is not None:
            await self._sandbox.kill()
            self._sandbox = None

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
