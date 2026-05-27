"""Sandbox — unified interface for provisioning and running AI coding agents."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any, Coroutine, Literal, cast, overload

from harnessbox._internal.runtime import AgentRuntime
from harnessbox._internal.runtime import InteractiveSession as InteractiveSession
from harnessbox._internal.session import SandboxSession
from harnessbox._internal.workspace_mount import WorkspaceMount
from harnessbox.config.harness import HarnessTypeConfig, get_harness_type
from harnessbox.config.pipeline import SetupContext, SetupPipeline, build_setup_pipeline
from harnessbox.cost import CostMetrics
from harnessbox.events import EventBuffer
from harnessbox.lifecycle import RuntimeState
from harnessbox.process import AgentProcess
from harnessbox.providers import CommandResult, SandboxProvider
from harnessbox.security.events import EventHandler, EventType
from harnessbox.security.policy import SecurityPolicy
from harnessbox.streaming import EventType as StreamEventType
from harnessbox.streaming import UniversalEvent
from harnessbox.types import AgentResponse
from harnessbox.workspace import Workspace

_log = logging.getLogger("harnessbox.sandbox")


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
        snapshot_id: str | None = None,
        initial_sequence: int = 0,
    ) -> None:
        """Create a sandbox for running AI coding agents.

        Args:
            client: Provider instance or name string (e.g., ``"e2b"``).
            security_policy: Deny rules and credential guards for the agent.
            harness: Agent harness type (``"claude-code"``, ``"codex"``, etc.).
            system_prompt: Agent system prompt. ``str`` = raw content,
                ``Path`` = read from local file. Placed at the harness's
                system prompt location (e.g., ``/workspace/CLAUDE.md``).
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
        self._timeout = timeout
        self._event_handler = event_handler
        self._skip_permissions = skip_permissions
        self._event_buffer = EventBuffer(
            storage=storage, session_id=session_id, initial_sequence=initial_sequence
        )
        self._session_timeout = session_timeout
        self._session_lock = session_lock
        self._snapshot_id = snapshot_id

        # Workspace mount collaborator (resolvers + git facade)
        self._mount = WorkspaceMount(
            harness_config=self._harness_config,
            workspace=workspace,
            system_prompt=system_prompt,
            files=files,
            env_vars=env_vars,
            dirs=dirs,
            setup_script=setup_script,
            cwd=cwd,
        )

        # Lifecycle collaborator
        self._session = SandboxSession(
            provider=self._provider,
            event_handler=event_handler,
            event_buffer=self._event_buffer,
            session_timeout=session_timeout,
            session_lock=session_lock,
        )

        # Agent execution collaborator
        self._runtime = AgentRuntime(
            provider=self._provider,
            harness_config=self._harness_config,
            event_buffer=self._event_buffer,
            model=model,
            one_shot=one_shot,
            skip_permissions=skip_permissions,
            timeout=timeout,
        )
        self._wire_runtime_callbacks()

    def _wire_runtime_callbacks(self) -> None:
        """Connect AgentRuntime to SandboxSession and WorkspaceMount via callbacks."""
        self._runtime._on_sandbox_dead = self._session.mark_dead
        self._runtime._start_idle_timer = self._session.start_idle_timer
        self._runtime._cancel_idle_timer = self._session.cancel_idle_timer
        self._runtime._get_state = lambda: self._session.state
        self._runtime._get_cwd = lambda: self._mount.cwd
        self._runtime._get_paused_sandbox_id = lambda: self._session.paused_sandbox_id
        self._runtime._resume_sandbox = self.resume
        self._runtime._clear_paused_id = lambda: setattr(self._session, "paused_sandbox_id", None)
        self._session._get_agent_session_id = lambda: self._runtime.agent_session_id
        self._session.set_stop_agent(self._stop_agent_process)

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
        """Return the underlying sandbox provider instance."""
        return self._provider

    @property
    def sandbox_id(self) -> str | None:
        """Return the provider's sandbox ID, or None if not yet created."""
        return self._provider.sandbox_id

    @property
    def state(self) -> RuntimeState:
        """Return the current lifecycle state of the sandbox."""
        return self._session.state

    @property
    def harness_config(self) -> HarnessTypeConfig:
        """Return the harness type configuration for this sandbox."""
        return self._harness_config

    @property
    def agent_session_id(self) -> str | None:
        """Return the agent session ID once a prompt has been run."""
        return self._runtime.agent_session_id

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
        return self._runtime.cost_metrics

    # Internal attribute delegation to collaborators
    @property
    def _state(self) -> RuntimeState:
        return self._session.state

    @_state.setter
    def _state(self, value: RuntimeState) -> None:
        self._session.state = value

    @property
    def _agent_session_id(self) -> str | None:
        return self._runtime.agent_session_id

    @_agent_session_id.setter
    def _agent_session_id(self, value: str | None) -> None:
        self._runtime.agent_session_id = value

    @property
    def _agent_process(self) -> AgentProcess | None:
        return self._runtime.agent_process

    @_agent_process.setter
    def _agent_process(self, value: AgentProcess | None) -> None:
        self._runtime.agent_process = value

    @_agent_process.deleter
    def _agent_process(self) -> None:
        self._runtime.agent_process = None

    @property
    def _idle_timer_task(self) -> asyncio.Task[None] | None:
        return self._session._idle_timer_task

    @_idle_timer_task.setter
    def _idle_timer_task(self, value: asyncio.Task[None] | None) -> None:
        self._session._idle_timer_task = value

    @property
    def _paused_sandbox_id(self) -> str | None:
        return self._session.paused_sandbox_id

    @_paused_sandbox_id.setter
    def _paused_sandbox_id(self, value: str | None) -> None:
        self._session.paused_sandbox_id = value

    @property
    def _cwd(self) -> str:
        return self._mount.cwd

    @_cwd.setter
    def _cwd(self, value: str) -> None:
        self._mount.cwd = value

    @property
    def _workspace(self) -> Workspace | None:
        return self._mount.workspace

    @property
    def _files(self) -> dict[str, str]:
        return self._mount._files

    @property
    def _cost_metrics(self) -> CostMetrics:
        return self._runtime._cost_metrics

    @_cost_metrics.setter
    def _cost_metrics(self, value: CostMetrics) -> None:
        self._runtime._cost_metrics = value

    # ------------------------------------------------------------------
    # State management (delegated to SandboxSession)
    # ------------------------------------------------------------------

    def _transition(self, target: RuntimeState) -> None:
        self._session.transition(target)

    async def _emit_event(
        self,
        event_type: EventType,
        *,
        action: str,
        resource: str | None = None,
        reason: str = "",
        **metadata: Any,
    ) -> None:
        await self._session.emit_event(
            event_type, action=action, resource=resource, reason=reason, **metadata
        )

    async def _push_lifecycle_event(self, event_type: StreamEventType, **metadata: Any) -> None:
        await self._session.push_lifecycle_event(event_type, **metadata)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _build_setup_context(self) -> SetupContext:
        """Build the SetupContext from Sandbox configuration.

        Pure: does not mutate Sandbox state, safe to call from dry_run().
        """
        return self._mount.build_setup_context(
            provider=self._provider,
            security_policy=self._security_policy,
            timeout=self._timeout,
            snapshot_id=self._snapshot_id,
        )

    def _build_pipeline(self) -> SetupPipeline:
        """Build the setup pipeline for this sandbox."""
        return build_setup_pipeline()

    async def setup(self) -> None:
        """Create the sandbox, inject all files and config.

        Transitions: STARTING -> ACTIVE

        Uses a sequential pipeline:
        create sandbox -> check tools -> workspace root -> workspace inject ->
        build manifest -> create dirs -> inject files -> hook permissions ->
        setup script -> ACTIVE.

        Agent behavior files (system prompt, skills, plugins) are written
        AFTER workspace injection so they take precedence over repo contents.
        """
        ctx = self._build_setup_context()
        pipeline = self._build_pipeline()

        await pipeline.execute(ctx)

        self._mount.sync_from_setup_context(ctx)
        await self._session.activate()

    def dry_run(self) -> list[str]:
        """Return the list of setup steps that would execute.

        Useful for testing and debugging the setup sequence without
        actually provisioning a sandbox.
        """
        ctx = self._build_setup_context()
        pipeline = self._build_pipeline()
        return pipeline.dry_run(ctx)

    def _snapshot_process_metrics(self) -> None:
        """Preserve cost metrics before discarding the agent process."""
        self._runtime.snapshot_process_metrics()

    async def _stop_agent_process(self) -> None:
        """Stop the agent process and snapshot metrics. Used as callback for SandboxSession."""
        await self._runtime.stop_agent_process()

    async def kill(self) -> None:
        """Destroy the sandbox. Idempotent from terminal states."""
        await self._session.kill()

    async def pause(self) -> str:
        """Pause the sandbox, preserving state. Returns sandbox_id."""
        return await self._session.pause()

    async def resume(self, sandbox_id: str) -> None:
        """Resume a paused sandbox."""
        await self._session.resume(sandbox_id)

    async def hibernate(self) -> str:
        """Pause the sandbox using VM-style lifecycle terminology."""
        return await self._session.hibernate()

    async def wake(self, sandbox_id: str | None = None) -> None:
        """Resume a hibernated sandbox.

        If *sandbox_id* is omitted, resumes the most recently paused sandbox.
        """
        await self._session.wake(sandbox_id)

    async def create_snapshot(self) -> str:
        """Create a snapshot of the sandbox's current filesystem state.

        Returns:
            snapshot_id for later restoration
        """
        return await self._session.create_snapshot()

    async def create_vm_snapshot(self) -> str:
        """Create a VM snapshot of the sandbox filesystem state."""
        return await self._session.create_vm_snapshot()

    # -- Idle timer --

    def _start_idle_timer(self) -> None:
        self._session.start_idle_timer()

    def _cancel_idle_timer(self) -> None:
        self._session.cancel_idle_timer()

    async def _on_idle_timeout(self) -> None:
        await self._session._on_idle_timeout()

    async def _do_idle_pause(self) -> None:
        await self._session._do_idle_pause()

    async def end(self) -> None:
        """Gracefully end the session."""
        await self._session.end()

    # ------------------------------------------------------------------
    # Agent execution (delegated to AgentRuntime)
    # ------------------------------------------------------------------

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
            return self._runtime.send_message(input, stream=False)
        return self._runtime.send_message(input, stream=True)

    async def _stream_oneshot(self, prompt: str) -> AsyncGenerator[str, None]:
        """Delegate to runtime."""
        async for line in self._runtime._stream_oneshot(prompt):
            yield line

    async def _ensure_agent_ready(self) -> None:
        """Delegate to runtime."""
        await self._runtime._ensure_agent_ready()

    @staticmethod
    def _parse_context_output(text: str) -> dict[str, Any] | None:
        """Parse the markdown output from /context into structured data."""
        from harnessbox.status import parse_context_output

        return parse_context_output(text)

    async def start_interactive_session(self) -> InteractiveSession:
        """Start a live interactive terminal session via PTY.

        Requires a PTY-capable provider (e.g., E2B). For multi-turn
        structured conversations, use repeated ``send_message()``
        calls instead (automatic ``--resume`` support).
        """
        return await self._runtime.start_interactive_session()

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
    # Git operations facade (delegated to WorkspaceMount)
    # ------------------------------------------------------------------

    async def rename_branch(self, new_name: str) -> None:
        """Rename the workspace branch in the sandbox."""
        await self._mount.rename_branch(self._provider, new_name)

    async def create_pr(self, title: str, body: str = "") -> dict[str, str]:
        """Commit, push, and create a GitHub PR. Returns {"url": "..."}."""
        return await self._mount.create_pr(self._provider, title, body)

    async def check_pr_status(self) -> dict[str, Any]:
        """Check PR status via gh CLI. Returns {state, merged, ci_status, url, number}."""
        return await self._mount.check_pr_status(self._provider)

    async def diff(self) -> str:
        """Return unified diff of changes since clone (or last snapshot restore)."""
        return await self._mount.diff(self._provider)

    async def diff_stat(self) -> dict[str, int]:
        """Return insertions/deletions since clone."""
        return await self._mount.diff_stat(self._provider)

    async def commit_count(self) -> int:
        """Return number of commits since clone."""
        return await self._mount.commit_count(self._provider)

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
