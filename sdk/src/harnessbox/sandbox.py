"""Sandbox — unified interface for provisioning and running AI coding agents."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from harnessbox.config.harness import HarnessTypeConfig, get_harness_type
from harnessbox.config.manifest import build_manifest
from harnessbox.events import EventBuffer
from harnessbox.lifecycle import InvalidTransitionError, SessionState, validate_transition
from harnessbox.process import AgentProcess
from harnessbox.providers import CommandResult, SandboxProvider
from harnessbox.security.events import EventHandler, EventType, SandboxEvent
from harnessbox.security.policy import SecurityPolicy
from harnessbox.streaming import EventType as StreamEventType
from harnessbox.streaming import StreamParser, UniversalEvent
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
        return self._pid

    async def send(self, message: str) -> None:
        await self._provider.pty_send(self._pid, (message + "\n").encode())

    async def stream_output(self) -> AsyncGenerator[bytes, None]:
        while True:
            data = await self._queue.get()
            if data is None:
                break
            yield data

    async def close(self) -> None:
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
        self._state = SessionState.STARTING
        self._workspace = workspace
        self._setup_script = setup_script
        self._event_handler = event_handler
        self._skip_permissions = skip_permissions
        self._cwd = cwd or self._harness_config.workspace_root
        self._agent_session_id: str | None = None
        self._event_buffer = EventBuffer()
        self._agent_process: AgentProcess | None = None
        self.unpushed_files: dict[str, str] | None = None
        self._session_timeout = session_timeout
        self._session_lock = session_lock
        self._idle_timer_task: asyncio.Task[None] | None = None
        self._paused_sandbox_id: str | None = None

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

    @property
    def agent_session_id(self) -> str | None:
        return self._agent_session_id

    @property
    def event_buffer(self) -> EventBuffer:
        return self._event_buffer

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

    async def _push_lifecycle_event(self, event_type: StreamEventType, **metadata: Any) -> None:
        event = UniversalEvent(
            event_id=str(uuid.uuid4()),
            sequence=self._event_buffer.latest_sequence + 1,
            timestamp=datetime.now(timezone.utc).isoformat(),
            session_id=self._agent_session_id or self.sandbox_id or "",
            event_type=event_type,
            metadata=metadata,
        )
        await self._event_buffer.push(event)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def setup(self) -> None:
        """Create the sandbox, inject all files and config.

        Transitions: STARTING -> ACTIVE

        Ordering: create sandbox -> dirs -> workspace inject -> files ->
        security hooks -> skill installs -> setup script -> ACTIVE.

        Agent behavior files (system prompt, skills, plugins) are written
        AFTER workspace injection so they take precedence over repo contents.
        """
        resolved_skills = self._resolve_skills()
        resolved_plugins = self._resolve_plugins()

        manifest = build_manifest(
            harness_config=self._harness_config,
            security_policy=self._security_policy,
            workspace_root=self._harness_config.workspace_root,
            env_vars=self._env_vars,
            dirs=self._dirs,
            files=self._files,
            system_prompt=self._system_prompt_content,
            skills=resolved_skills,
            plugins=resolved_plugins,
        )

        await self._provider.create(
            env_vars=manifest.env_vars,
            timeout=self._timeout,
        )

        for d in manifest.dirs:
            await self._provider.make_dir(d)

        if self._workspace:
            await self._workspace.inject(self._provider, self._harness_config.workspace_root)

        for path, content in manifest.files.items():
            await self._provider.write_file(path, content)

        if self._security_policy and self._harness_config.hooks_dir:
            hook_path = (
                f"{self._harness_config.workspace_root}/"
                f"{self._harness_config.hooks_dir}/guard_bash.py"
            )
            if hook_path in manifest.files:
                await self._provider.run_command(f"chmod +x {hook_path}")

        if self._skill_installs and self._harness_config.skill_install_cmd:
            for skill_spec in self._skill_installs:
                cmd = f"{self._harness_config.skill_install_cmd} {skill_spec}"
                result = await self._provider.run_command(
                    cmd, cwd=self._harness_config.workspace_root
                )
                if result.exit_code != 0:
                    raise RuntimeError(f"Skill install failed ({skill_spec}): {result.stderr}")

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
        await self._push_lifecycle_event(StreamEventType.SESSION_STARTED)

    async def kill(self) -> None:
        """Destroy the sandbox. Idempotent from terminal states."""
        if self._state in (SessionState.MERGED, SessionState.FAILED):
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
            self._state = SessionState.FAILED

    async def pause(self) -> str:
        """Pause the sandbox, preserving state. Returns sandbox_id."""
        self._transition(SessionState.PAUSED)
        return await self._provider.pause()

    async def resume(self, sandbox_id: str) -> None:
        """Resume a paused sandbox."""
        await self._provider.resume(sandbox_id)
        self._transition(SessionState.ACTIVE)

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
        if self._state != SessionState.ACTIVE:
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
        self._transition(SessionState.ENDING)
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
        self._state = SessionState.MERGED
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

    async def run_prompt(self, prompt: str) -> AsyncGenerator[str, None]:
        """Run the agent with a one-shot prompt and yield raw output lines.

        For typed stream events, use ``run_prompt_events()`` instead.
        Automatically resumes the previous session if one exists.
        """
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
        cmd = self._harness_config.build_oneshot_command(
            escaped_prompt,
            skip_permissions=self._skip_permissions,
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
        if self._state == SessionState.PAUSED and self._paused_sandbox_id:
            _log.info("Resuming paused sandbox %s", self._paused_sandbox_id)
            await self.resume(self._paused_sandbox_id)
            self._paused_sandbox_id = None

        if not self._agent_process or not self._agent_process.is_running:
            cmd = self._harness_config.build_persistent_command(
                skip_permissions=self._skip_permissions,
                plugin_dirs=self._plugin_dirs or None,
                session_id=self._agent_session_id,
            )
            self._agent_process = AgentProcess(self._provider, StreamParser(persistent=True))
            await self._agent_process.start(cmd, cwd=self._cwd)
            _log.info("Persistent agent process started")

    async def run_prompt_events(self, prompt: str) -> AsyncGenerator[UniversalEvent, None]:
        """Run the agent and yield typed universal stream events.

        In persistent mode (Claude Code with ``--input-format stream-json``),
        sends the prompt to the living process's stdin and streams the turn's
        events. The process stays alive for the next call.

        In one-shot mode (fallback), spawns a new process per prompt with
        ``--resume`` for conversation continuity.
        """
        self._cancel_idle_timer()

        use_persistent = self._harness_config.supports_persistent and hasattr(
            self._provider, "start_persistent"
        )
        if use_persistent:
            await self._ensure_agent_ready()

            try:
                await self._agent_process.send_prompt(prompt)
            except RuntimeError:
                _log.warning("Agent process dead (sandbox timeout?), restarting with --resume")
                self._agent_process = None
                await self._ensure_agent_ready()
                await self._agent_process.send_prompt(prompt)

            async for event in self._agent_process.stream_turn():
                if event.session_id:
                    self._agent_session_id = event.session_id
                await self._event_buffer.push(event)
                yield event

            status_event = await self._poll_session_status()
            if status_event:
                await self._event_buffer.push(status_event)
                yield status_event

            self._start_idle_timer()
        else:
            parser = StreamParser(session_id=self._agent_session_id or "")
            async for line in self.run_prompt(prompt):
                for event in parser.parse_line(line):
                    if event.session_id:
                        self._agent_session_id = event.session_id
                    await self._event_buffer.push(event)
                    yield event

    async def _poll_session_status(self) -> UniversalEvent | None:
        """Poll /context and /cost after a turn and emit a STATUS event."""
        if not self._agent_process or not self._agent_process.is_running:
            return None
        try:
            context_data = await self._agent_process.send_command("/context", timeout=5)
            cost_data = await self._agent_process.send_command("/cost", timeout=5)
        except Exception as e:
            _log.warning("Status poll failed: %s", e)
            return None

        _log.info("Context data keys: %s", list(context_data.keys()))
        _log.info("Cost data keys: %s", list(cost_data.keys()))

        metadata: dict[str, Any] = {}

        context_output = context_data.get("output", "")
        if context_output:
            parsed = self._parse_context_output(context_output)
            if parsed:
                metadata["context"] = parsed

        cost_output = cost_data.get("output", "")
        if cost_output:
            metadata["cost_text"] = cost_output

        total_cost = cost_data.get("total_cost_usd")
        if total_cost is not None:
            metadata["total_cost_usd"] = total_cost

        if not metadata:
            _log.info("Status poll: no metadata collected")
            return None

        _log.info("Status poll: emitting STATUS event with %s", list(metadata.keys()))
        return UniversalEvent(
            event_id=str(uuid.uuid4()),
            sequence=self._event_buffer.latest_sequence + 1,
            timestamp=datetime.now(timezone.utc).isoformat(),
            session_id=self._agent_session_id or "",
            event_type=StreamEventType.STATUS,
            metadata=metadata,
        )

    @staticmethod
    def _parse_context_output(text: str) -> dict[str, Any] | None:
        """Parse the markdown output from /context into structured data."""
        import re

        result: dict[str, Any] = {}
        tokens_match = re.search(r"\*\*Tokens:\*\*\s*([\d.]+)k\s*/\s*([\d.]+)k\s*\((\d+)%\)", text)
        if tokens_match:
            used_k = float(tokens_match.group(1))
            total_k = float(tokens_match.group(2))
            percent = int(tokens_match.group(3))
            result["tokens_used"] = int(used_k * 1000)
            result["context_window"] = int(total_k * 1000)
            result["percent_used"] = percent

        model_match = re.search(r"\*\*Model:\*\*\s*(\S+)", text)
        if model_match:
            result["model"] = model_match.group(1)

        return result if result else None

    async def start_interactive_session(self) -> InteractiveSession:
        """Start a live interactive terminal session via PTY.

        Requires a PTY-capable provider (e.g., E2B). For multi-turn
        structured conversations, use repeated ``run_prompt_events()``
        calls instead (automatic ``--resume`` support).
        """
        if self._state != SessionState.ACTIVE:
            hint = (
                " Call 'await sandbox.setup()' first."
                if self._state == SessionState.STARTING
                else ""
            )
            raise RuntimeError(
                f"Cannot start interactive session: sandbox is in "
                f"{self._state.value!r} state.{hint}"
            )

        if not hasattr(self._provider, "pty_create"):
            raise RuntimeError(
                f"Provider {type(self._provider).__name__} does not support "
                f"interactive sessions (no PTY). Use run_prompt_events() with "
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
