"""Sandbox — unified interface for provisioning and running AI coding agents."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any, cast

from harnessbox._setup import build_manifest
from harnessbox.harness import HarnessTypeConfig, get_harness_type
from harnessbox.lifecycle import InvalidTransitionError, SessionState, validate_transition
from harnessbox.providers import CommandResult, SandboxProvider
from harnessbox.security import SecurityPolicy
from harnessbox.workspace import Workspace


class Sandbox:
    """Unified sandbox for running AI coding agents across providers.

    Orchestrates provider lifecycle, agent-type-aware config generation,
    security policy injection, and command execution.

    Example::

        from harnessbox import Sandbox, SecurityPolicy

        sandbox = Sandbox(
            client="e2b",
            api_key="...",
            security_policy=SecurityPolicy(deny_network=True),
            harness="claude-code",
            env_vars={"CLAUDE_CODE_USE_BEDROCK": "1"},
            files={"/workspace/CLAUDE.md": "You are a helpful assistant."},
        )

        await sandbox.setup()
        async for line in sandbox.run_prompt("Analyze the code"):
            print(line)
        await sandbox.kill()
    """

    def __init__(
        self,
        client: SandboxProvider | str,
        *,
        security_policy: SecurityPolicy | None = None,
        harness: str = "claude-code",
        env_vars: dict[str, str] | None = None,
        dirs: list[str] | None = None,
        files: dict[str, str] | None = None,
        timeout: int = 300,
        api_key: str | None = None,
        template: str | None = None,
        workspace: Workspace | None = None,
        setup_script: str | None = None,
    ) -> None:
        if isinstance(client, str):
            self._provider = self._resolve_string_provider(
                client, api_key=api_key, template=template, timeout=timeout
            )
        elif isinstance(client, SandboxProvider):
            self._provider = client
        else:
            raise TypeError(
                f"client must be a SandboxProvider instance or a provider name string, "
                f"got {type(client).__name__}"
            )

        self._harness_config: HarnessTypeConfig = get_harness_type(harness)
        self._security_policy = security_policy
        self._env_vars = dict(env_vars) if env_vars else {}
        self._dirs = list(dirs) if dirs else []
        self._files = dict(files) if files else {}
        self._timeout = timeout
        self._state = SessionState.STARTING
        self._interactive_pid: int | None = None
        self._workspace = workspace
        self._setup_script = setup_script
        self.unpushed_files: dict[str, str] | None = None

    @staticmethod
    def _resolve_string_provider(
        name: str,
        *,
        api_key: str | None,
        template: str | None,
        timeout: int,
    ) -> SandboxProvider:
        from harnessbox._providers import get_provider_class

        provider_cls = get_provider_class(name)
        kwargs: dict[str, Any] = {}
        if api_key is not None:
            kwargs["api_key"] = api_key
        if template is not None:
            kwargs["template"] = template
        kwargs["timeout"] = timeout
        return cast(SandboxProvider, provider_cls(**kwargs))

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def provider(self) -> SandboxProvider:
        return self._provider

    @property
    def sandbox_id(self) -> str | None:
        return self._provider.sandbox_id

    @property
    def state(self) -> SessionState:
        return self._state

    @property
    def harness_config(self) -> HarnessTypeConfig:
        return self._harness_config

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------

    def _transition(self, target: SessionState) -> None:
        if not validate_transition(self._state, target):
            raise InvalidTransitionError(self._state, target)
        self._state = target

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def setup(self, *, system_prompt: str | None = None) -> None:
        """Create the sandbox, inject all files and config.

        Transitions: STARTING -> ACTIVE

        Args:
            system_prompt: Optional system prompt content. Can also be provided
                via files dict in constructor.
        """
        manifest = build_manifest(
            harness_config=self._harness_config,
            security_policy=self._security_policy,
            workspace_root=self._harness_config.workspace_root,
            env_vars=self._env_vars,
            dirs=self._dirs,
            files=self._files,
            system_prompt=system_prompt,
        )

        await self._provider.create(
            env_vars=manifest.env_vars,
            timeout=self._timeout,
        )

        for d in manifest.dirs:
            await self._provider.make_dir(d)

        for path, content in manifest.files.items():
            await self._provider.write_file(path, content)

        if self._security_policy and self._harness_config.hooks_dir:
            hook_path = (
                f"{self._harness_config.workspace_root}/"
                f"{self._harness_config.hooks_dir}/guard_bash.py"
            )
            if hook_path in manifest.files:
                await self._provider.run_command(f"chmod +x {hook_path}")

        if self._workspace:
            await self._workspace.inject(
                self._provider, self._harness_config.workspace_root
            )

        if self._setup_script:
            result = await self._provider.run_command(
                self._setup_script,
                cwd=self._harness_config.workspace_root,
            )
            if result.exit_code != 0:
                raise RuntimeError(
                    f"Setup script failed (exit {result.exit_code}): {result.stderr}"
                )

        self._transition(SessionState.ACTIVE)

    async def kill(self) -> None:
        """Destroy the sandbox. Idempotent from terminal states."""
        if self._state in (SessionState.MERGED, SessionState.FAILED):
            return
        if self._workspace:
            try:
                await self._workspace.extract(
                    self._provider, self._harness_config.workspace_root
                )
                if hasattr(self._workspace, "push_error") and self._workspace.push_error:
                    await self._recover_unpushed_files()
            except Exception:
                pass
        try:
            await self._provider.kill()
        finally:
            self._state = SessionState.FAILED

    async def pause(self) -> str:
        """Pause the sandbox, preserving state. Returns sandbox_id."""
        self._transition(SessionState.PAUSED)
        return await self._provider.pause()

    async def resume(self, sandbox_id: str) -> None:
        """Resume a paused sandbox."""
        await self._provider.resume(sandbox_id)
        self._transition(SessionState.ACTIVE)

    async def end(self) -> None:
        """Gracefully end the session."""
        self._transition(SessionState.ENDING)
        if self._workspace:
            await self._workspace.extract(
                self._provider, self._harness_config.workspace_root
            )
            if hasattr(self._workspace, "push_error") and self._workspace.push_error:
                await self._recover_unpushed_files()
        await self._provider.kill()
        self._state = SessionState.MERGED

    async def _recover_unpushed_files(self) -> None:
        """Extract committed files when push fails."""
        result = await self._provider.run_command(
            "git diff --name-only HEAD~1 HEAD 2>/dev/null || git diff --name-only HEAD",
            cwd=self._harness_config.workspace_root,
        )
        if result.exit_code != 0 or not result.stdout.strip():
            return
        files: dict[str, str] = {}
        for line in result.stdout.strip().split("\n"):
            path = line.strip()
            if path:
                try:
                    content = await self._provider.read_file(
                        f"{self._harness_config.workspace_root}/{path}"
                    )
                    files[path] = content
                except Exception:
                    pass
        if files:
            self.unpushed_files = files

    # ------------------------------------------------------------------
    # Agent execution
    # ------------------------------------------------------------------

    async def run_prompt(self, prompt: str) -> AsyncGenerator[str, None]:
        """Run the agent with a one-shot prompt and yield output lines."""
        if self._state != SessionState.ACTIVE:
            raise RuntimeError(f"Cannot run prompt in state {self._state.value!r}")

        escaped_prompt = json.dumps(prompt)
        cmd = self._harness_config.cli_oneshot_template.format(prompt=escaped_prompt)

        async for line in self._provider.stream_command(
            cmd,
            cwd=self._harness_config.workspace_root,
            timeout=self._timeout,
        ):
            yield line

    async def start_interactive(self) -> int:
        """Start the agent in interactive mode. Returns the process PID."""
        if self._state != SessionState.ACTIVE:
            raise RuntimeError(f"Cannot start interactive in state {self._state.value!r}")

        cmd = self._harness_config.cli_interactive_template
        handle = await self._provider.run_background(
            cmd, cwd=self._harness_config.workspace_root
        )
        self._interactive_pid = handle.pid
        return handle.pid

    async def send_message(self, message: str) -> None:
        """Send a message to an interactive agent session."""
        if self._interactive_pid is None:
            raise RuntimeError("Interactive mode not started. Call start_interactive() first.")
        await self._provider.send_stdin(self._interactive_pid, message + "\n")

    # ------------------------------------------------------------------
    # Command execution
    # ------------------------------------------------------------------

    async def run_command(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int | None = None,
    ) -> CommandResult:
        """Run an arbitrary command in the sandbox."""
        return await self._provider.run_command(
            command,
            cwd=cwd or self._harness_config.workspace_root,
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    async def write_file(self, path: str, content: str) -> None:
        await self._provider.write_file(path, content)

    async def write_files(self, files: dict[str, str]) -> None:
        for path, content in files.items():
            await self._provider.write_file(path, content)

    async def read_file(self, path: str) -> str:
        return await self._provider.read_file(path)

    async def make_dir(self, path: str) -> None:
        await self._provider.make_dir(path)

    async def extract_files(
        self, directory: str, pattern: str = "*"
    ) -> dict[str, str]:
        """Extract text files from a sandbox directory."""
        result = await self._provider.run_command(
            f"find {directory} -type f -name '{pattern}' -not -name '.*' | sort",
            cwd=self._harness_config.workspace_root,
        )

        if not result.stdout.strip():
            return {}

        files: dict[str, str] = {}
        for line in result.stdout.strip().split("\n"):
            path = line.strip()
            if path:
                try:
                    content = await self._provider.read_file(path)
                    files[path] = content
                except Exception:
                    pass
        return files

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> Sandbox:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        await self.kill()
