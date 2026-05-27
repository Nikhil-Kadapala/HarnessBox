"""AgentRuntime — agent process management, streaming, and PTY."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator, Callable
from datetime import datetime, timezone
from typing import Any, Coroutine, Literal, overload

from harnessbox.config.harness import HarnessTypeConfig
from harnessbox.cost import CostMetrics
from harnessbox.events import EventBuffer
from harnessbox.lifecycle import RuntimeState
from harnessbox.process import AgentProcess
from harnessbox.providers import PTYCapable, SandboxDeadError, SandboxProvider
from harnessbox.streaming import EventType as StreamEventType
from harnessbox.streaming import StreamParser, UniversalEvent
from harnessbox.types import AgentResponse

_log = logging.getLogger("harnessbox._internal.runtime")


class InteractiveSession:
    """Bidirectional interactive agent session backed by a provider PTY."""

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


class AgentRuntime:
    """Manages agent process lifecycle, streaming, and interactive sessions.

    Receives injected dependencies (provider, config, event buffer) and callbacks
    for lifecycle coordination (idle timer, dead state transition).
    """

    def __init__(
        self,
        provider: SandboxProvider,
        harness_config: HarnessTypeConfig,
        event_buffer: EventBuffer,
        *,
        model: str | None = None,
        one_shot: bool = False,
        skip_permissions: bool = False,
        timeout: int = 300,
    ) -> None:
        self._provider = provider
        self._harness_config = harness_config
        self._event_buffer = event_buffer
        self._model = model
        self._one_shot = one_shot
        self._skip_permissions = skip_permissions
        self._timeout = timeout

        self._agent_process: AgentProcess | None = None
        self._agent_session_id: str | None = None
        self._cost_metrics = CostMetrics()

        # Cache provider capability checks (avoids hasattr per-event in hot path)
        self._has_notify_turn_start = hasattr(provider, "notify_turn_start")
        self._has_notify_turn_end = hasattr(provider, "notify_turn_end")
        self._has_extend_timeout = hasattr(provider, "maybe_extend_timeout")

        # Callbacks set by Sandbox to coordinate with SandboxSession
        self._on_sandbox_dead: Callable[[], None] | None = None
        self._start_idle_timer: Callable[[], None] | None = None
        self._cancel_idle_timer: Callable[[], None] | None = None
        self._get_state: Callable[[], RuntimeState] | None = None
        self._get_cwd: Callable[[], str] | None = None
        self._get_paused_sandbox_id: Callable[[], str | None] | None = None
        self._resume_sandbox: Callable[[str], Coroutine[Any, Any, None]] | None = None
        self._clear_paused_id: Callable[[], None] | None = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def agent_process(self) -> AgentProcess | None:
        return self._agent_process

    @agent_process.setter
    def agent_process(self, value: AgentProcess | None) -> None:
        self._agent_process = value

    @property
    def agent_session_id(self) -> str | None:
        return self._agent_session_id

    @agent_session_id.setter
    def agent_session_id(self, value: str | None) -> None:
        self._agent_session_id = value

    @property
    def cost_metrics(self) -> CostMetrics:
        if self._agent_process:
            return self._agent_process.cost_metrics
        return self._cost_metrics

    @cost_metrics.setter
    def cost_metrics(self, value: CostMetrics) -> None:
        self._cost_metrics = value

    # ------------------------------------------------------------------
    # Agent process management
    # ------------------------------------------------------------------

    def snapshot_process_metrics(self) -> None:
        if self._agent_process:
            self._cost_metrics = self._agent_process.cost_metrics

    async def stop_agent_process(self) -> None:
        """Stop the agent process and preserve metrics."""
        if self._agent_process:
            self.snapshot_process_metrics()
            try:
                await self._agent_process.stop()
            except Exception:
                pass
            self._agent_process = None

    def _require_active(self, action: str) -> None:
        """Raise if sandbox is not in ACTIVE state."""
        state = self._get_state() if self._get_state else RuntimeState.ACTIVE
        if state != RuntimeState.ACTIVE:
            hint = " Call 'await sandbox.setup()' first." if state == RuntimeState.STARTING else ""
            raise RuntimeError(f"Cannot {action}: sandbox is in {state.value!r} state.{hint}")

    async def _stream_oneshot(self, prompt: str) -> AsyncGenerator[str, None]:
        """Spawn a one-shot agent process and yield raw NDJSON lines."""
        self._require_active("run prompt")

        cwd = self._get_cwd() if self._get_cwd else self._harness_config.workspace_root

        escaped_prompt = json.dumps(prompt)
        cmd = self._harness_config.build_oneshot_command(
            escaped_prompt,
            skip_permissions=self._skip_permissions,
            model=self._model,
            session_id=self._agent_session_id,
        )
        _log.info("Running command: %s", cmd[:300])

        async for line in self._provider.stream_command(
            cmd,
            cwd=cwd,
            timeout=self._timeout,
        ):
            self._try_extract_session_id(line)
            yield line

    async def _ensure_agent_ready(self) -> None:
        """Ensure the persistent agent process is running and ready for prompts."""
        state = self._get_state() if self._get_state else RuntimeState.ACTIVE
        paused_id = self._get_paused_sandbox_id() if self._get_paused_sandbox_id else None

        if state == RuntimeState.PAUSED and paused_id:
            _log.info("Resuming paused sandbox %s", paused_id)
            if self._resume_sandbox:
                await self._resume_sandbox(paused_id)
            if self._clear_paused_id:
                self._clear_paused_id()

        cwd = self._get_cwd() if self._get_cwd else self._harness_config.workspace_root

        if not self._agent_process or not self._agent_process.is_running:
            cmd = self._harness_config.build_session_command(
                skip_permissions=self._skip_permissions,
                model=self._model,
                session_id=self._agent_session_id,
            )
            self._agent_process = AgentProcess(self._provider, StreamParser(persistent=True))
            await self._agent_process.start(cmd, cwd=cwd)
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
        if not stream:
            return self._collect_response(input)
        return self._stream_events(input)

    async def _collect_response(self, prompt: str) -> AgentResponse:
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
        """Stream typed events from the agent for a single turn."""
        try:
            if self._cancel_idle_timer:
                self._cancel_idle_timer()

            use_persistent = self._harness_config.supports_persistent and not self._one_shot
            if use_persistent:
                await self._ensure_agent_ready()
                assert self._agent_process is not None

                if self._has_notify_turn_start:
                    self._provider.notify_turn_start()  # type: ignore[attr-defined]

                try:
                    await self._agent_process.send_prompt(prompt)
                except RuntimeError:
                    _log.warning("Agent process dead (sandbox timeout?), restarting with --resume")
                    self.snapshot_process_metrics()
                    self._agent_process = None
                    await self._ensure_agent_ready()
                    assert self._agent_process is not None
                    self._agent_process.restore_cost_metrics(self._cost_metrics)
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
                        if self._has_notify_turn_end:
                            self._provider.notify_turn_end()  # type: ignore[attr-defined]
                    event = await self._event_buffer.push(event)
                    yield event

                    if self._has_extend_timeout:
                        await self._provider.maybe_extend_timeout()  # type: ignore[attr-defined]

                result_model_usage = (
                    (last_turn_end.metadata or {}).get("model_usage") if last_turn_end else None
                )
                skip_cost = bool(result_model_usage)

                sid = self._agent_session_id or ""
                if skip_cost and last_turn_end:
                    cost_event = self._agent_process.cost_update_from_result(
                        last_turn_end, session_id=sid
                    )
                    if cost_event:
                        cost_event = await self._event_buffer.push(cost_event)
                        yield cost_event

                for status_event in await self._agent_process.poll_status(
                    skip_cost=skip_cost, session_id=sid
                ):
                    status_event = await self._event_buffer.push(status_event)
                    yield status_event

                if self._start_idle_timer:
                    self._start_idle_timer()
            else:
                parser = StreamParser(session_id=self._agent_session_id or "")
                async for line in self._stream_oneshot(prompt):
                    for event in parser.parse_line(line):
                        if event.session_id:
                            self._agent_session_id = event.session_id
                        event = await self._event_buffer.push(event)
                        yield event

        except SandboxDeadError as e:
            if self._has_notify_turn_end:
                self._provider.notify_turn_end()  # type: ignore[attr-defined]
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
            error_event = await self._event_buffer.push(error_event)
            yield error_event

            if self._on_sandbox_dead:
                self._on_sandbox_dead()
            return

    async def start_interactive_session(self) -> InteractiveSession:
        """Start a live interactive terminal session via PTY."""
        self._require_active("start interactive session")

        if not isinstance(self._provider, PTYCapable):
            raise RuntimeError(
                f"Provider {type(self._provider).__name__} does not support "
                f"interactive sessions (no PTY). Use send_message() with "
                f"automatic --resume for multi-turn conversations."
            )

        cwd = self._get_cwd() if self._get_cwd else self._harness_config.workspace_root

        queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def on_data(data: bytes) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, data)

        cmd = self._harness_config.build_interactive_command(
            skip_permissions=self._skip_permissions,
        )
        pid = await self._provider.pty_create(
            on_data,
            cwd=cwd,
        )
        await self._provider.pty_send(pid, f"exec {cmd}\n".encode())

        return InteractiveSession(pid, self._provider, queue)

    def _try_extract_session_id(self, line: str) -> None:
        try:
            data = json.loads(line)
            sid = data.get("session_id")
            if sid:
                self._agent_session_id = sid
        except (json.JSONDecodeError, ValueError, AttributeError):
            pass
