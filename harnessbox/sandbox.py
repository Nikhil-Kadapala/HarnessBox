"""Sandbox — unified interface for provisioning and running AI coding agents."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from harnessbox.config.harness import HarnessTypeConfig, get_harness_type
from harnessbox.config.manifest import build_manifest
from harnessbox.lifecycle import InvalidTransitionError, SessionState, validate_transition
from harnessbox.providers import CommandResult, SandboxProvider
from harnessbox.security.events import EventHandler, EventType, SandboxEvent
from harnessbox.security.policy import SecurityPolicy
from harnessbox.workspace import Workspace


class Sandbox:
    """Unified sandbox for running AI coding agents across providers.

    Orchestrates provider lifecycle, agent-type-aware config generation,
    security policy injection, and command execution.

    Example::

        from pathlib import Path
        from harnessbox import Sandbox, SecurityPolicy

        sandbox = Sandbox(
            client="e2b",
            api_key="...",
            security_policy=SecurityPolicy(deny_network=True),
            harness="claude-code",
            # Inject local files by path, or pass raw content as strings
            files=["./prompts/CLAUDE.md", "./config/rules.json"],
            # Or mix both: files={"/workspace/CLAUDE.md": Path("./CLAUDE.md"),
            #                     "/workspace/data.json": '{"key": "value"}'}
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
        files: dict[str, str | Path] | list[str | Path] | None = None,
        timeout: int = 300,
        api_key: str | None = None,
        template: str | None = None,
        workspace: Workspace | None = None,
        setup_script: str | None = None,
        event_handler: EventHandler | None = None,
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
        self._files = self._resolve_files(files, self._harness_config.workspace_root)
        self._timeout = timeout
        self._state = SessionState.STARTING
        self._interactive_pid: int | None = None
        self._workspace = workspace
        self._setup_script = setup_script
        self._event_handler = event_handler
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

    @staticmethod
    def _resolve_files(
        files: dict[str, str | Path] | list[str | Path] | None,
        workspace_root: str,
    ) -> dict[str, str]:
        """Normalize the files parameter into a dict of sandbox_path → content.

        Accepts three forms:
        - ``None`` → empty dict
        - ``list[str | Path]`` → each path is read from disk and placed at
          ``{workspace_root}/{filename}``
        - ``dict[str, str | Path]`` → str values are raw content (injected as-is),
          Path values are read from disk and injected at the dict key path
        """
        if files is None:
            return {}

        resolved: dict[str, str] = {}

        if isinstance(files, list):
            for entry in files:
                p = Path(entry)
                if not p.is_file():
                    raise FileNotFoundError(
                        f"Cannot inject {p}: file not found. "
                        f"Pass a dict with raw content if the file doesn't exist on disk."
                    )
                sandbox_path = f"{workspace_root}/{p.name}"
                resolved[sandbox_path] = p.read_text(encoding="utf-8")
            return resolved

        for sandbox_path, value in files.items():
            if isinstance(value, Path):
                if not value.is_file():
                    raise FileNotFoundError(
                        f"Cannot inject {value}: file not found. "
                        f"Pass a str value for dynamically generated content."
                    )
                resolved[sandbox_path] = value.read_text(encoding="utf-8")
            else:
                resolved[sandbox_path] = value

        return resolved

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

    async def _emit_event(
        self,
        event_type: EventType,
        *,
        action: str,
        resource: str | None = None,
        reason: str = "",
        **metadata: Any,
    ) -> None:
        if self._event_handler is None:
            return
        event = SandboxEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            sandbox_id=self.sandbox_id,
            event_type=event_type,
            action=action,
            resource=resource,
            reason=reason,
            metadata=metadata,
        )
        try:
            await self._event_handler.handle(event)
        except Exception:
            pass

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
            await self._workspace.inject(self._provider, self._harness_config.workspace_root)

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
        await self._emit_event(EventType.SETUP_COMPLETE, action="setup")

    async def kill(self) -> None:
        """Destroy the sandbox. Idempotent from terminal states."""
        if self._state in (SessionState.MERGED, SessionState.FAILED):
            return
        if self._workspace:
            try:
                await self._workspace.extract(self._provider, self._harness_config.workspace_root)
                if hasattr(self._workspace, "push_error") and self._workspace.push_error:
                    await self._recover_unpushed_files()
            except Exception:
                pass
        await self._emit_event(EventType.SESSION_END, action="kill")
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
            await self._workspace.extract(self._provider, self._harness_config.workspace_root)
            if hasattr(self._workspace, "push_error") and self._workspace.push_error:
                await self._recover_unpushed_files()
        await self._provider.kill()
        self._state = SessionState.MERGED
        await self._emit_event(EventType.SESSION_END, action="end")

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
            hint = (
                " Call 'await sandbox.setup()' first."
                if self._state == SessionState.STARTING
                else ""
            )
            raise RuntimeError(
                f"Cannot run prompt: sandbox is in {self._state.value!r} state.{hint}"
            )

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
            hint = (
                " Call 'await sandbox.setup()' first."
                if self._state == SessionState.STARTING
                else ""
            )
            raise RuntimeError(
                f"Cannot start interactive mode: sandbox is in {self._state.value!r} state.{hint}"
            )

        cmd = self._harness_config.cli_interactive_template
        handle = await self._provider.run_background(cmd, cwd=self._harness_config.workspace_root)
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
        result = await self._provider.run_command(
            command,
            cwd=cwd or self._harness_config.workspace_root,
            timeout=timeout,
        )
        await self._emit_event(EventType.COMMAND_RUN, action="run_command", resource=command)
        return result

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

    async def extract_files(self, directory: str, pattern: str = "*") -> dict[str, str]:
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
