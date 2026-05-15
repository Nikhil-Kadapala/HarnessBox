"""Sandbox — unified interface for provisioning and running AI coding agents."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Coroutine, Literal, cast, overload

from harnessbox.config.harness import HarnessTypeConfig, get_harness_type
from harnessbox.config.manifest import build_manifest
from harnessbox.cost import CostMetrics, ModelCost, parse_cost_data
from harnessbox.events import EventBuffer
from harnessbox.lifecycle import InvalidTransitionError, WorkspaceState, validate_transition
from harnessbox.process import AgentProcess
from harnessbox.providers import CommandResult, PTYCapable, SandboxDeadError, SandboxProvider
from harnessbox.security.events import EventHandler, EventType, SandboxEvent
from harnessbox.security.policy import SecurityPolicy
from harnessbox.streaming import EventType as StreamEventType
from harnessbox.streaming import StreamParser, UniversalEvent
from harnessbox.types import AgentResponse
from harnessbox.workspace import Workspace

_log = logging.getLogger("harnessbox.sandbox")


class InteractiveSession:
    """Bidirectional interactive agent session backed by a provider PTY.

    Use ``send()`` to send messages and ``stream_output()`` to receive
    raw terminal output (bytes, may include ANSI escape codes).
    """

    def __init__(self, pid: int, provider: Any, output_queue: asyncio.Queue[bytes | None]) -> None:
        self._pid = pid
        self._provider = provider
        self._queue = output_queue

    @property
    def pid(self) -> int:
        """Return the PTY process ID for this interactive session."""
        return self._pid

    async def send(self, message: str) -> None:
        """Send a message (with trailing newline) to the agent's stdin."""
        await self._provider.pty_send(self._pid, (message + "\n").encode())

    async def stream_output(self) -> AsyncGenerator[bytes, None]:
        """Yield raw terminal output bytes until the session closes."""
        while True:
            data = await self._queue.get()
            if data is None:
                break
            yield data

    async def close(self) -> None:
        """Kill the PTY process and signal end-of-stream."""
        await self._provider.pty_kill(self._pid)
        self._queue.put_nowait(None)


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
        async for event in sandbox.send_message("Analyze the code"):
            print(event.delta or "", end="")
        await sandbox.kill()
    """

    def __init__(
        self,
        client: SandboxProvider | str,
        *,
        security_policy: SecurityPolicy | None = None,
        harness: str = "claude-code",
        model: str | None = None,
        one_shot: bool = False,
        system_prompt: str | Path | None = None,
        skills: list[str | Path] | None = None,
        skill_installs: list[str] | None = None,
        plugins: list[str | Path] | None = None,
        env_vars: dict[str, str] | None = None,
        dirs: list[str] | None = None,
        files: dict[str, str | Path] | list[str | Path] | None = None,
        timeout: int = 300,
        api_key: str | None = None,
        template: str | None = None,
        workspace: Workspace | None = None,
        setup_script: str | None = None,
        event_handler: EventHandler | None = None,
        skip_permissions: bool = False,
        cwd: str | None = None,
        session_timeout: int = 900,
        session_lock: asyncio.Lock | None = None,
        storage: Any = None,  # StorageBackend | None (TYPE_CHECKING import to avoid circular)
        session_id: str = "",
    ) -> None:
        """Create a sandbox for running AI coding agents.

        Args:
            client: Provider instance or name string (e.g., ``"e2b"``).
            security_policy: Deny rules and credential guards for the agent.
            harness: Agent harness type (``"claude-code"``, ``"codex"``, etc.).
            system_prompt: Agent system prompt. ``str`` = raw content,
                ``Path`` = read from local file. Placed at the harness's
                system prompt location (e.g., ``/workspace/CLAUDE.md``).
            skills: Local skill files or directories to inject. Single ``.md``
                files become ``{skills_dir}/{stem}/SKILL.md``. Directories
                are copied as-is into the skills directory.
            skill_installs: Registry skills to install via
                ``npx skills add`` during setup (e.g.,
                ``["anthropics/skills --skill frontend-design"]``).
            plugins: Local plugin directories to inject and load via
                the harness's plugin flag (e.g., ``--plugin-dir``).
            env_vars: Environment variables for the sandbox.
            dirs: Additional directories to create in the sandbox.
            files: Generic files to inject. ``list[Path]`` = read and place
                at ``{workspace_root}/{filename}``. ``dict[str, str|Path]`` =
                inject at specific sandbox paths.
            timeout: Sandbox creation and command timeout in seconds.
            api_key: Provider API key (when using string client).
            template: Override the provider template (default: harness-aware).
            workspace: Git workspace to clone into the sandbox.
            setup_script: Shell command to run after all files are injected.
            event_handler: Receives sandbox lifecycle events.
            skip_permissions: If True, skip the agent's permission prompts
                (safe inside isolated sandboxes, required for headless mode).
            cwd: Working directory for agent commands. Defaults to
                workspace_root. Useful when working in a subdirectory
                (e.g., a git worktree at ``/workspace/feat-branch``).
        """
        self._harness_config: HarnessTypeConfig = get_harness_type(harness)
        self._model = model
        self._one_shot = one_shot

        if isinstance(client, str):
            effective_template = template or self._harness_config.default_template
            self._provider = self._resolve_string_provider(
                client, api_key=api_key, template=effective_template, timeout=timeout
            )
        elif isinstance(client, SandboxProvider):
            self._provider = client
        else:
            raise TypeError(
                f"client must be a SandboxProvider instance or a provider name string, "
                f"got {type(client).__name__}"
            )
        self._security_policy = security_policy
        self._system_prompt_content = self._resolve_prompt(system_prompt)
        self._skills = skills or []
        self._skill_installs = skill_installs or []
        self._plugins = plugins or []
        self._plugin_dirs: list[str] = []
        self._env_vars = dict(env_vars) if env_vars else {}
        self._dirs = list(dirs) if dirs else []
        self._files = self._resolve_files(files, self._harness_config.workspace_root)
        self._timeout = timeout
        self._state = WorkspaceState.STARTING
        self._workspace = workspace
        self._setup_script = setup_script
        self._event_handler = event_handler
        self._skip_permissions = skip_permissions
        self._cwd = cwd or self._harness_config.workspace_root
        self._agent_session_id: str | None = None
        self._event_buffer = EventBuffer(storage=storage, session_id=session_id)
        self._agent_process: AgentProcess | None = None
        self.unpushed_files: dict[str, str] | None = None
        self._session_timeout = session_timeout
        self._session_lock = session_lock
        self._idle_timer_task: asyncio.Task[None] | None = None
        self._paused_sandbox_id: str | None = None
        self._cost_metrics = CostMetrics()

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

    @staticmethod
    def _resolve_prompt(prompt: str | Path | None) -> str | None:
        if prompt is None:
            return None
        if isinstance(prompt, Path):
            if not prompt.is_file():
                raise FileNotFoundError(f"System prompt not found: {prompt}")
            return prompt.read_text(encoding="utf-8")
        return prompt

    def _resolve_skills(self) -> dict[str, str] | None:
        if not self._skills:
            return None
        if not self._harness_config.skills_dir:
            return None
        resolved: dict[str, str] = {}
        skills_base = f"{self._harness_config.workspace_root}/{self._harness_config.skills_dir}"
        for entry in self._skills:
            p = Path(entry)
            if p.is_dir():
                for file in p.rglob("*"):
                    if file.is_file():
                        try:
                            content = file.read_text(encoding="utf-8")
                        except UnicodeDecodeError:
                            continue
                        rel = file.relative_to(p)
                        resolved[f"{skills_base}/{p.name}/{rel}"] = content
            elif p.is_file():
                resolved[f"{skills_base}/{p.stem}/SKILL.md"] = p.read_text(encoding="utf-8")
            else:
                raise FileNotFoundError(f"Skill not found: {p}")
        return resolved

    def _resolve_plugins(self) -> dict[str, str] | None:
        if not self._plugins:
            return None
        resolved: dict[str, str] = {}
        for plugin_path in self._plugins:
            p = Path(plugin_path)
            if not p.is_dir():
                raise FileNotFoundError(f"Plugin directory not found: {p}")
            plugin_sandbox_dir = (
                f"{self._harness_config.workspace_root}/.harnessbox/plugins/{p.name}"
            )
            self._plugin_dirs.append(plugin_sandbox_dir)
            for file in p.rglob("*"):
                if file.is_file():
                    try:
                        content = file.read_text(encoding="utf-8")
                    except UnicodeDecodeError:
                        continue
                    rel = file.relative_to(p)
                    resolved[f"{plugin_sandbox_dir}/{rel}"] = content
        return resolved

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def provider(self) -> SandboxProvider:
        """Return the underlying sandbox provider instance."""
        return self._provider

    @property
    def sandbox_id(self) -> str | None:
        """Return the provider's sandbox ID, or None if not yet created."""
        return self._provider.sandbox_id

    @property
    def state(self) -> WorkspaceState:
        """Return the current lifecycle state of the sandbox."""
        return self._state

    @property
    def harness_config(self) -> HarnessTypeConfig:
        """Return the harness type configuration for this sandbox."""
        return self._harness_config

    @property
    def agent_session_id(self) -> str | None:
        """Return the agent session ID once a prompt has been run."""
        return self._agent_session_id

    @property
    def event_buffer(self) -> EventBuffer:
        """Return the event buffer used for SSE streaming and replay."""
        return self._event_buffer

    @property
    def cost_metrics(self) -> CostMetrics:
        """Return the current cost metrics for this session.

        Returns an immutable snapshot of accumulated costs across all turns.
        Costs include total USD spent and per-model breakdown with input/output
        tokens.

        Only available in persistent mode. One-shot mode does not track costs.

        Example::

            metrics = sandbox.cost_metrics
            print(f"Total: ${metrics.total_cost_usd:.4f}")
            print(f"Turns: {metrics.turn_count}")
            for model, cost in metrics.per_model.items():
                print(f"  {model}: ${cost.cost_usd:.4f}")
        """
        return self._cost_metrics

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------

    def _transition(self, target: WorkspaceState) -> None:
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

    async def _push_lifecycle_event(self, event_type: StreamEventType, **metadata: Any) -> None:
        event = UniversalEvent(
            event_id=str(uuid.uuid4()),
            sequence=0,
            timestamp=datetime.now(timezone.utc).isoformat(),
            session_id=self._agent_session_id or self.sandbox_id or "",
            event_type=event_type,
            metadata=metadata,
        )
        await self._event_buffer.push(event)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _check_installed_tools(self) -> dict[str, bool]:
        """Check which tools are pre-installed in E2B base image.

        This is a diagnostic check to determine if E2B templates would provide
        meaningful performance improvement. Logs results but doesn't affect setup.
        """
        tools = {
            "git": "git",
            "python3": "python3",
            "node": "node",
            "npm": "npm",
            "bun": "bun",
            "gh": "gh",
            "uv": "uv",
            "tree": "tree",
            "rg": "rg",  # ripgrep
            "fd": "fd",
        }

        installed = {}
        for name, cmd in tools.items():
            result = await self._provider.run_command(
                f"command -v {cmd} >/dev/null 2>&1 && echo FOUND || echo MISSING"
            )
            installed[name] = "FOUND" in result.stdout

        # Log as structured data for easy parsing
        installed_names = [name for name, found in installed.items() if found]
        missing_names = [name for name, found in installed.items() if not found]

        _log.info(
            f"Pre-installed tools: {', '.join(installed_names) if installed_names else 'none'}"
        )
        if missing_names:
            _log.info(f"Missing tools: {', '.join(missing_names)}")

        return installed

    async def setup(self) -> None:
        """Create the sandbox, inject all files and config.

        Transitions: STARTING -> ACTIVE

        Ordering: create sandbox -> dirs -> workspace inject -> files ->
        security hooks -> skill installs -> setup script -> ACTIVE.

        Agent behavior files (system prompt, skills, plugins) are written
        AFTER workspace injection so they take precedence over repo contents.
        """
        setup_start = time.time()

        # Phase 1: Create sandbox
        sandbox_start = time.time()
        await self._provider.create(
            env_vars=self._env_vars or {},
            timeout=self._timeout,
        )
        _log.info(f"sandbox_creation took {time.time() - sandbox_start:.2f}s")

        # Phase 2: Check pre-installed tools (skip for mock providers in tests)
        if not hasattr(self._provider, "_commands"):  # Skip MockProvider
            await self._check_installed_tools()

        # Phase 3: Create workspace root directory
        workspace_root_start = time.time()
        await self._provider.make_dir(self._harness_config.workspace_root)
        _log.info(f"workspace_root_creation took {time.time() - workspace_root_start:.2f}s")

        # Phase 4: Inject workspace (git clone into subdirectory)
        if self._workspace:
            workspace_start = time.time()
            await self._workspace.inject(self._provider, self._harness_config.workspace_root)
            if hasattr(self._workspace, "clone_dir_name") and self._workspace.clone_dir_name:
                self._cwd = (
                    f"{self._harness_config.workspace_root}/{self._workspace.clone_dir_name}"
                )
            _log.info(f"workspace_inject took {time.time() - workspace_start:.2f}s")

        # Determine the actual working directory for manifest files
        # If we cloned into a subdirectory, use that. Otherwise use workspace_root.
        manifest_target_dir = self._cwd if self._cwd else self._harness_config.workspace_root

        resolved_skills = self._resolve_skills()
        resolved_plugins = self._resolve_plugins()

        # Phase 4: Build manifest (using the actual working directory)
        manifest_start = time.time()
        manifest = build_manifest(
            harness_config=self._harness_config,
            security_policy=self._security_policy,
            workspace_root=manifest_target_dir,
            env_vars=self._env_vars,
            dirs=self._dirs,
            files=self._files,
            system_prompt=self._system_prompt_content,
            skills=resolved_skills,
            plugins=resolved_plugins,
        )
        _log.info(f"manifest_build took {time.time() - manifest_start:.2f}s")

        # Phase 5: Create directories
        dirs_start = time.time()
        for d in manifest.dirs:
            await self._provider.make_dir(d)
        _log.info(f"directory_creation took {time.time() - dirs_start:.2f}s")

        # Phase 6: Inject manifest files (into cloned directory)
        files_start = time.time()
        for path, content in manifest.files.items():
            await self._provider.write_file(path, content)
        _log.info(f"manifest_file_injection took {time.time() - files_start:.2f}s")

        # Phase 7: Set hook permissions
        hooks_start = time.time()
        if self._security_policy and self._harness_config.hooks_dir:
            hook_path = f"{manifest_target_dir}/{self._harness_config.hooks_dir}/guard_bash.py"
            if hook_path in manifest.files:
                await self._provider.run_command(f"chmod +x {hook_path}")
        _log.info(f"hook_setup took {time.time() - hooks_start:.2f}s")

        # Phase 8: Install skills
        skills_start = time.time()
        if self._skill_installs and self._harness_config.skill_install_cmd:
            for skill_spec in self._skill_installs:
                cmd = f"{self._harness_config.skill_install_cmd} {skill_spec}"
                result = await self._provider.run_command(cmd, cwd=manifest_target_dir)
                if result.exit_code != 0:
                    raise RuntimeError(f"Skill install failed ({skill_spec}): {result.stderr}")
        _log.info(f"skill_install took {time.time() - skills_start:.2f}s")

        # Phase 9: Run setup script
        script_start = time.time()
        if self._setup_script:
            result = await self._provider.run_command(
                self._setup_script,
                cwd=manifest_target_dir,
            )
            if result.exit_code != 0:
                raise RuntimeError(
                    f"Setup script failed (exit {result.exit_code}): {result.stderr}"
                )
        _log.info(f"setup_script took {time.time() - script_start:.2f}s")

        total_time = time.time() - setup_start
        _log.info(f"setup_total took {total_time:.2f}s")

        self._transition(WorkspaceState.ACTIVE)
        await self._emit_event(EventType.SETUP_COMPLETE, action="setup")
        await self._push_lifecycle_event(StreamEventType.SESSION_STARTED)

    async def kill(self) -> None:
        """Destroy the sandbox. Idempotent from terminal states."""
        if self._state in (WorkspaceState.MERGED, WorkspaceState.FAILED):
            return
        if self._agent_process:
            try:
                await self._agent_process.stop()
            except Exception:
                pass
            self._agent_process = None
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
            self._state = WorkspaceState.FAILED

    async def pause(self) -> str:
        """Pause the sandbox, preserving state. Returns sandbox_id."""
        self._transition(WorkspaceState.PAUSED)
        return await self._provider.pause()

    async def resume(self, sandbox_id: str) -> None:
        """Resume a paused sandbox."""
        await self._provider.resume(sandbox_id)
        self._transition(WorkspaceState.ACTIVE)

    async def create_snapshot(self) -> str:
        """Create a snapshot of the sandbox's current filesystem state.

        Returns:
            snapshot_id for later restoration
        """
        return await self._provider.create_snapshot()

    # -- Idle timer --

    def _start_idle_timer(self) -> None:
        self._cancel_idle_timer()
        if self._session_timeout > 0:
            self._idle_timer_task = asyncio.create_task(self._on_idle_timeout())

    def _cancel_idle_timer(self) -> None:
        if self._idle_timer_task and not self._idle_timer_task.done():
            self._idle_timer_task.cancel()
        self._idle_timer_task = None

    async def _on_idle_timeout(self) -> None:
        await asyncio.sleep(self._session_timeout)
        if self._session_lock:
            async with self._session_lock:
                await self._do_idle_pause()
        else:
            await self._do_idle_pause()

    async def _do_idle_pause(self) -> None:
        if self._state != WorkspaceState.ACTIVE:
            return
        _log.info("Idle timeout (%ds), pausing sandbox", self._session_timeout)
        if self._agent_process:
            try:
                await self._agent_process.stop()
            except Exception:
                pass
            self._agent_process = None
        self._paused_sandbox_id = await self.pause()

    async def end(self) -> None:
        """Gracefully end the session."""
        self._transition(WorkspaceState.ENDING)
        if self._agent_process:
            try:
                await self._agent_process.stop()
            except Exception:
                pass
            self._agent_process = None
        if self._workspace:
            await self._workspace.extract(self._provider, self._harness_config.workspace_root)
            if hasattr(self._workspace, "push_error") and self._workspace.push_error:
                await self._recover_unpushed_files()
        await self._provider.kill()
        self._state = WorkspaceState.MERGED
        await self._emit_event(EventType.SESSION_END, action="end")
        await self._push_lifecycle_event(StreamEventType.SESSION_ENDED)
        await self._event_buffer.close()

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

    async def _stream_oneshot(self, prompt: str) -> AsyncGenerator[str, None]:
        """Spawn a one-shot agent process and yield raw NDJSON lines.

        Used internally by ``send_message()`` in one-shot mode.
        Automatically resumes the previous session if one exists.
        """
        if self._state != WorkspaceState.ACTIVE:
            hint = (
                " Call 'await sandbox.setup()' first."
                if self._state == WorkspaceState.STARTING
                else ""
            )
            raise RuntimeError(
                f"Cannot run prompt: sandbox is in {self._state.value!r} state.{hint}"
            )

        escaped_prompt = json.dumps(prompt)
        cmd = self._harness_config.build_oneshot_command(
            escaped_prompt,
            skip_permissions=self._skip_permissions,
            model=self._model,
            session_id=self._agent_session_id,
            plugin_dirs=self._plugin_dirs or None,
        )
        _log.info("Running command: %s", cmd[:300])

        async for line in self._provider.stream_command(
            cmd,
            cwd=self._cwd,
            timeout=self._timeout,
        ):
            self._try_extract_session_id(line)
            yield line

    async def _ensure_agent_ready(self) -> None:
        """Ensure the persistent agent process is running and ready for prompts.

        Handles first start, restart after idle-pause, and restart after
        sandbox timeout (agent process died, sandbox auto-resumed by E2B).
        """
        if self._state == WorkspaceState.PAUSED and self._paused_sandbox_id:
            _log.info("Resuming paused sandbox %s", self._paused_sandbox_id)
            await self.resume(self._paused_sandbox_id)
            self._paused_sandbox_id = None

        if not self._agent_process or not self._agent_process.is_running:
            cmd = self._harness_config.build_session_command(
                skip_permissions=self._skip_permissions,
                model=self._model,
                plugin_dirs=self._plugin_dirs or None,
                session_id=self._agent_session_id,
            )
            self._agent_process = AgentProcess(self._provider, StreamParser(persistent=True))
            await self._agent_process.start(cmd, cwd=self._cwd)
            _log.info("Persistent agent process started")

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
        """Send a message to the agent and get the response.

        Args:
            input: The user message to send.
            stream: If True (default), returns an async generator yielding
                events as they arrive. If False, returns an awaitable that
                resolves to an ``AgentResponse`` when the turn completes.

        Usage::

            # Streaming (default)
            async for event in sandbox.send_message("fix the bug"):
                print(event.delta or "", end="")

            # Non-streaming
            response = await sandbox.send_message("fix the bug", stream=False)
            print(response.text)
        """
        if not stream:
            return self._collect_response(input)
        return self._stream_events(input)

    async def _collect_response(self, prompt: str) -> AgentResponse:
        """Stream internally and return accumulated AgentResponse."""
        events: list[UniversalEvent] = []
        text_parts: list[str] = []
        cost_usd: float | None = None
        duration_ms: int | None = None
        session_id = ""

        async for event in self._stream_events(prompt):
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

    async def _stream_events(self, prompt: str) -> AsyncGenerator[UniversalEvent, None]:
        """Internal: stream typed events from the agent for a single turn.

        Uses persistent mode when supported, falls back to one-shot with
        ``--resume`` for conversation continuity.
        """
        try:
            self._cancel_idle_timer()

            use_persistent = self._harness_config.supports_persistent and not self._one_shot
            if use_persistent:
                await self._ensure_agent_ready()

                try:
                    await self._agent_process.send_prompt(prompt)
                except RuntimeError:
                    _log.warning("Agent process dead (sandbox timeout?), restarting with --resume")
                    self._agent_process = None
                    await self._ensure_agent_ready()
                    await self._agent_process.send_prompt(prompt)

                last_turn_end: UniversalEvent | None = None
                async for event in self._agent_process.stream_turn():
                    if event.session_id:
                        self._agent_session_id = event.session_id
                    if event.event_type in (
                        StreamEventType.TURN_ENDED,
                        StreamEventType.SESSION_ENDED,
                    ):
                        last_turn_end = event
                    await self._event_buffer.push(event)
                    yield event

                result_model_usage = (
                    (last_turn_end.metadata or {}).get("model_usage") if last_turn_end else None
                )
                skip_cost = bool(result_model_usage)

                if skip_cost and last_turn_end:
                    cost_event = self._cost_update_from_result(last_turn_end)
                    if cost_event:
                        await self._event_buffer.push(cost_event)
                        yield cost_event

                for status_event in await self._poll_status_events(skip_cost=skip_cost):
                    await self._event_buffer.push(status_event)
                    yield status_event

                self._start_idle_timer()
            else:
                parser = StreamParser(session_id=self._agent_session_id or "")
                async for line in self._stream_oneshot(prompt):
                    for event in parser.parse_line(line):
                        if event.session_id:
                            self._agent_session_id = event.session_id
                        await self._event_buffer.push(event)
                        yield event

        except SandboxDeadError as e:
            _log.error(
                f"Sandbox {self._provider.sandbox_id} is dead: {e}",
                extra={"sandbox_id": self._provider.sandbox_id},
            )

            error_event = UniversalEvent(
                event_id=str(uuid.uuid4()),
                sequence=0,
                timestamp=datetime.now(timezone.utc).isoformat(),
                session_id=self._agent_session_id or "",
                event_type=StreamEventType.ERROR,
                error_message="Sandbox has timed out or been destroyed. Create a new session.",
                metadata={
                    "error_code": "SANDBOX_DEAD",
                    "error_details": str(e),
                    "recoverable": False,
                },
            )
            await self._event_buffer.push(error_event)
            yield error_event

            try:
                self._transition(WorkspaceState.FAILED)
            except InvalidTransitionError as transition_err:
                _log.debug(
                    f"Could not transition to FAILED (already in {self._state.value}): {transition_err}"
                )

            return

    def _cost_update_from_result(self, turn_end_event: UniversalEvent) -> UniversalEvent | None:
        """Build a COST_UPDATE event from enriched result metadata (snapshot overwrite)."""
        metadata = turn_end_event.metadata or {}
        model_usage = metadata.get("model_usage", {})

        if not model_usage:
            return None

        total_cost = turn_end_event.cost_usd

        per_model: dict[str, ModelCost] = {}
        for model_name, usage in model_usage.items():
            if not isinstance(usage, dict):
                continue
            input_tokens = usage.get("inputTokens", usage.get("input_tokens", 0))
            output_tokens = usage.get("outputTokens", usage.get("output_tokens", 0))
            per_model[model_name] = ModelCost(
                input_tokens=int(input_tokens or 0),
                output_tokens=int(output_tokens or 0),
                cost_usd=0.0,
            )

        self._cost_metrics = CostMetrics(
            total_cost_usd=float(total_cost) if total_cost else self._cost_metrics.total_cost_usd,
            per_model=per_model,
            turn_count=self._cost_metrics.turn_count + 1,
            last_updated=datetime.now(timezone.utc).isoformat(),
        )

        return UniversalEvent(
            event_id=str(uuid.uuid4()),
            sequence=0,
            timestamp=datetime.now(timezone.utc).isoformat(),
            session_id=self._agent_session_id or "",
            event_type=StreamEventType.COST_UPDATE,
            metadata={
                "total_cost_usd": self._cost_metrics.total_cost_usd,
                "turn_count": self._cost_metrics.turn_count,
                "per_model": {
                    model: {
                        "input_tokens": mc.input_tokens,
                        "output_tokens": mc.output_tokens,
                        "cost_usd": mc.cost_usd,
                    }
                    for model, mc in self._cost_metrics.per_model.items()
                },
            },
        )

    async def _poll_status_events(self, *, skip_cost: bool = False) -> list[UniversalEvent]:
        """Poll /context and optionally /cost after a turn, emit typed events."""
        if not self._agent_process or not self._agent_process.is_running:
            return []
        try:
            context_data = await self._agent_process.send_command("/context", timeout=5)
            cost_data = (
                await self._agent_process.send_command("/cost", timeout=5) if not skip_cost else {}
            )
        except asyncio.TimeoutError:
            _log.warning("Status poll timed out")
            return []
        except Exception as e:
            _log.warning("Status poll failed: %s", e)
            return []

        events: list[UniversalEvent] = []
        session_id = self._agent_session_id or ""
        now = datetime.now(timezone.utc).isoformat()

        # --- CONTEXT_UPDATE event ---
        context_output = context_data.get("output", "")
        if context_output:
            parsed = self._parse_context_output(context_output)
            if parsed:
                events.append(
                    UniversalEvent(
                        event_id=str(uuid.uuid4()),
                        sequence=0,
                        timestamp=now,
                        session_id=session_id,
                        event_type=StreamEventType.CONTEXT_UPDATE,
                        metadata=parsed,
                    )
                )

        # --- COST_UPDATE event (only when not already emitted from result) ---
        if not skip_cost and cost_data:
            try:
                parsed_cost = parse_cost_data(cost_data)
                if parsed_cost:
                    self._cost_metrics = parsed_cost
                    events.append(
                        UniversalEvent(
                            event_id=str(uuid.uuid4()),
                            sequence=0,
                            timestamp=now,
                            session_id=session_id,
                            event_type=StreamEventType.COST_UPDATE,
                            metadata={
                                "total_cost_usd": parsed_cost.total_cost_usd,
                                "turn_count": parsed_cost.turn_count,
                                "per_model": {
                                    model: {
                                        "input_tokens": mc.input_tokens,
                                        "output_tokens": mc.output_tokens,
                                        "cost_usd": mc.cost_usd,
                                    }
                                    for model, mc in parsed_cost.per_model.items()
                                },
                            },
                        )
                    )
            except Exception as e:
                _log.warning("Failed to parse cost data: %s", e)

        return events

    @staticmethod
    def _parse_context_output(text: str) -> dict[str, Any] | None:
        """Parse the markdown output from /context into structured data."""
        import re

        def parse_token_count(value: str, suffix: str | None = None) -> int:
            multiplier = 1
            if suffix:
                normalized_suffix = suffix.lower()
                if normalized_suffix == "k":
                    multiplier = 1_000
                elif normalized_suffix == "m":
                    multiplier = 1_000_000
            return int(float(value.replace(",", "")) * multiplier)

        result: dict[str, Any] = {}
        tokens_match = re.search(
            r"(?:\*\*)?Tokens:(?:\*\*)?\s*([\d,.]+)\s*([kKmM]?)\s*/\s*([\d,.]+)\s*([kKmM]?)\s*\((\d+)%\)",
            text,
            re.IGNORECASE,
        )
        if not tokens_match:
            tokens_match = re.search(
                r"\b([\d,.]+)\s*([kKmM])\s*/\s*([\d,.]+)\s*([kKmM])\s+tokens\s*\((\d+)%\)",
                text,
                re.IGNORECASE,
            )
        if tokens_match:
            percent = int(tokens_match.group(5))
            result["tokens_used"] = parse_token_count(tokens_match.group(1), tokens_match.group(2))
            result["context_window"] = parse_token_count(
                tokens_match.group(3), tokens_match.group(4)
            )
            result["percent_used"] = percent

        model_match = re.search(r"(?:\*\*)?Model:(?:\*\*)?\s*(\S+)", text, re.IGNORECASE)
        if not model_match:
            model_match = re.search(
                r"\b([A-Za-z][A-Za-z0-9 ._-]+)\s+\((?:[\d.]+[kKmM]\s+)?context\)",
                text,
                re.IGNORECASE,
            )
        if model_match:
            result["model"] = model_match.group(1).strip()

        category_labels = [
            ("system prompt", "system_prompt", "System prompt"),
            ("system tools", "system_tools", "System tools"),
            ("memory files", "memory_files", "Memory files"),
            ("tools", "tools", "Tools"),
            ("rules", "rules", "Rules"),
            ("skills", "skills", "Skills"),
            ("mcp", "mcp", "MCP"),
            ("subagents", "subagents", "Subagents"),
            ("messages", "messages", "Messages"),
            ("conversation", "conversation", "Conversation"),
            ("free space", "free_space", "Free space"),
            ("autocompact buffer", "autocompact_buffer", "Autocompact buffer"),
        ]
        categories: list[dict[str, Any]] = []
        seen_category_keys: set[str] = set()
        for raw_line in text.splitlines():
            line = raw_line.strip().strip("|").strip()
            if not line or "tokens:" in line.lower() or "model:" in line.lower():
                continue
            normalized_line = re.sub(r"[*_`]", "", line)
            for label, key, display_label in category_labels:
                if key in seen_category_keys:
                    continue
                category_match = re.search(
                    rf"\b{re.escape(label)}\b\s*(?:\||:|-|\u2014|\u2013)?\s*~?\$?([\d,.]+)\s*([kKmM]?)\s*(?:tokens?)?\b",
                    normalized_line,
                    re.IGNORECASE,
                )
                if not category_match:
                    continue
                categories.append(
                    {
                        "key": key,
                        "label": display_label,
                        "tokens": parse_token_count(
                            category_match.group(1),
                            category_match.group(2),
                        ),
                    }
                )
                seen_category_keys.add(key)
                break

        if categories:
            if any(category["key"] in {"system_tools", "free_space"} for category in categories):
                terminal_category_defaults = [
                    ("system_prompt", "System prompt"),
                    ("system_tools", "System tools"),
                    ("memory_files", "Memory files"),
                    ("skills", "Skills"),
                    ("messages", "Messages"),
                    ("free_space", "Free space"),
                    ("autocompact_buffer", "Autocompact buffer"),
                ]
                existing_categories = {category["key"]: category for category in categories}
                categories = [
                    existing_categories.get(
                        key,
                        {
                            "key": key,
                            "label": label,
                            "tokens": 0,
                        },
                    )
                    for key, label in terminal_category_defaults
                ]
            result["categories"] = categories

        return result if result else None

    async def start_interactive_session(self) -> InteractiveSession:
        """Start a live interactive terminal session via PTY.

        Requires a PTY-capable provider (e.g., E2B). For multi-turn
        structured conversations, use repeated ``send_message()``
        calls instead (automatic ``--resume`` support).
        """
        if self._state != WorkspaceState.ACTIVE:
            hint = (
                " Call 'await sandbox.setup()' first."
                if self._state == WorkspaceState.STARTING
                else ""
            )
            raise RuntimeError(
                f"Cannot start interactive session: sandbox is in "
                f"{self._state.value!r} state.{hint}"
            )

        if not isinstance(self._provider, PTYCapable):
            raise RuntimeError(
                f"Provider {type(self._provider).__name__} does not support "
                f"interactive sessions (no PTY). Use send_message() with "
                f"automatic --resume for multi-turn conversations."
            )

        queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def on_data(data: bytes) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, data)

        cmd = self._harness_config.build_interactive_command(
            skip_permissions=self._skip_permissions,
            plugin_dirs=self._plugin_dirs or None,
        )
        pid = await self._provider.pty_create(
            on_data,
            cwd=self._cwd,
        )
        await self._provider.pty_send(pid, f"exec {cmd}\n".encode())

        return InteractiveSession(pid, self._provider, queue)

    def _try_extract_session_id(self, line: str) -> None:
        """Best-effort extraction of session_id from raw output lines."""
        try:
            data = json.loads(line)
            sid = data.get("session_id")
            if sid:
                self._agent_session_id = sid
        except (json.JSONDecodeError, ValueError, AttributeError):
            pass

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
            cwd=cwd or self._cwd,
            timeout=timeout,
        )
        await self._emit_event(EventType.COMMAND_RUN, action="run_command", resource=command)
        return result

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    async def write_file(self, path: str, content: str) -> None:
        """Write text content to a file in the sandbox."""
        await self._provider.write_file(path, content)

    async def write_files(self, files: dict[str, str]) -> None:
        """Write multiple files to the sandbox from a path-to-content mapping."""
        for path, content in files.items():
            await self._provider.write_file(path, content)

    async def read_file(self, path: str) -> str:
        """Read and return text content from a file in the sandbox."""
        return await self._provider.read_file(path)

    async def make_dir(self, path: str) -> None:
        """Create a directory (and parents) in the sandbox."""
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
