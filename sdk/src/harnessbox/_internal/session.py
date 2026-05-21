"""SandboxSession — lifecycle state management for a sandbox instance."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable, Coroutine
from datetime import datetime, timezone
from typing import Any

from harnessbox.events import EventBuffer
from harnessbox.lifecycle import InvalidTransitionError, RuntimeState, validate_runtime_transition
from harnessbox.providers import SandboxProvider
from harnessbox.security.events import EventHandler, EventType, SandboxEvent
from harnessbox.streaming import EventType as StreamEventType
from harnessbox.streaming import UniversalEvent

_log = logging.getLogger("harnessbox._internal.session")

StopAgentFn = Callable[[], Coroutine[Any, Any, None]]


class SandboxSession:
    """Manages sandbox lifecycle state, idle timer, pause/resume/hibernate/wake, and snapshots.

    Delegates provider calls for pause/resume/kill but owns the RuntimeState machine
    and event emission.
    """

    def __init__(
        self,
        provider: SandboxProvider,
        event_handler: EventHandler | None,
        event_buffer: EventBuffer,
        session_timeout: int,
        session_lock: asyncio.Lock | None,
    ) -> None:
        self._provider = provider
        self._event_handler = event_handler
        self._event_buffer = event_buffer
        self._session_timeout = session_timeout
        self._session_lock = session_lock

        self._state = RuntimeState.STARTING
        self._idle_timer_task: asyncio.Task[None] | None = None
        self._paused_sandbox_id: str | None = None
        self._agent_session_id: str | None = None
        self._stop_agent: StopAgentFn | None = None

    @property
    def state(self) -> RuntimeState:
        return self._state

    @state.setter
    def state(self, value: RuntimeState) -> None:
        self._state = value

    @property
    def paused_sandbox_id(self) -> str | None:
        return self._paused_sandbox_id

    @paused_sandbox_id.setter
    def paused_sandbox_id(self, value: str | None) -> None:
        self._paused_sandbox_id = value

    @property
    def agent_session_id(self) -> str | None:
        return self._agent_session_id

    @agent_session_id.setter
    def agent_session_id(self, value: str | None) -> None:
        self._agent_session_id = value

    def set_stop_agent(self, fn: StopAgentFn) -> None:
        """Register the callback to stop the agent process before pausing/killing."""
        self._stop_agent = fn

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def transition(self, target: RuntimeState) -> None:
        if not validate_runtime_transition(self._state, target):
            raise InvalidTransitionError(self._state, target)
        self._state = target

    async def emit_event(
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
            sandbox_id=self._provider.sandbox_id,
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

    async def push_lifecycle_event(self, event_type: StreamEventType, **metadata: Any) -> None:
        event = UniversalEvent(
            event_id=str(uuid.uuid4()),
            sequence=0,
            timestamp=datetime.now(timezone.utc).isoformat(),
            session_id=self._agent_session_id or self._provider.sandbox_id or "",
            event_type=event_type,
            metadata=metadata,
        )
        await self._event_buffer.push(event)

    # ------------------------------------------------------------------
    # Lifecycle operations
    # ------------------------------------------------------------------

    async def activate(self) -> None:
        """Transition to ACTIVE after setup completes."""
        self.transition(RuntimeState.ACTIVE)
        await self.emit_event(EventType.SETUP_COMPLETE, action="setup")
        await self.push_lifecycle_event(StreamEventType.SESSION_STARTED)

    async def kill(self) -> None:
        """Destroy the sandbox. Idempotent from terminal states."""
        if self._state in (RuntimeState.ENDED, RuntimeState.DEAD):
            return
        if self._stop_agent:
            try:
                await self._stop_agent()
            except Exception:
                pass
        await self.emit_event(EventType.SESSION_END, action="kill")
        try:
            await self._provider.kill()
        finally:
            self._state = RuntimeState.DEAD

    async def pause(self) -> str:
        """Pause the sandbox, preserving state. Returns sandbox_id."""
        self.transition(RuntimeState.PAUSED)
        sandbox_id = await self._provider.pause()
        self._paused_sandbox_id = sandbox_id
        return sandbox_id

    async def resume(self, sandbox_id: str) -> None:
        """Resume a paused sandbox."""
        await self._provider.resume(sandbox_id)
        self._paused_sandbox_id = sandbox_id
        self.transition(RuntimeState.ACTIVE)

    async def hibernate(self) -> str:
        """Pause the sandbox using VM-style lifecycle terminology."""
        return await self.pause()

    async def wake(self, sandbox_id: str | None = None) -> None:
        """Resume a hibernated sandbox."""
        target = sandbox_id or self._paused_sandbox_id
        if not target:
            raise RuntimeError("No paused sandbox id is available to wake")
        await self.resume(target)

    async def create_snapshot(self) -> str:
        """Create a snapshot of the sandbox's current filesystem state."""
        return await self._provider.create_snapshot()

    async def create_vm_snapshot(self) -> str:
        """Create a VM snapshot of the sandbox filesystem state."""
        return await self.create_snapshot()

    async def end(self) -> None:
        """Gracefully end the session."""
        self.transition(RuntimeState.DYING)
        if self._stop_agent:
            try:
                await self._stop_agent()
            except Exception:
                pass
        await self._provider.kill()
        self._state = RuntimeState.ENDED
        await self.emit_event(EventType.SESSION_END, action="end")
        await self.push_lifecycle_event(StreamEventType.SESSION_ENDED)
        await self._event_buffer.close()

    # ------------------------------------------------------------------
    # Idle timer
    # ------------------------------------------------------------------

    def start_idle_timer(self) -> None:
        self.cancel_idle_timer()
        if self._session_timeout > 0:
            self._idle_timer_task = asyncio.create_task(self._on_idle_timeout())

    def cancel_idle_timer(self) -> None:
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
        if self._state != RuntimeState.ACTIVE:
            return
        _log.info("Idle timeout (%ds), pausing sandbox", self._session_timeout)
        if self._stop_agent:
            try:
                await self._stop_agent()
            except Exception:
                pass
        self._paused_sandbox_id = await self.pause()

    # ------------------------------------------------------------------
    # SandboxDeadError callback (used by AgentRuntime)
    # ------------------------------------------------------------------

    def mark_dead(self) -> None:
        """Called by AgentRuntime when SandboxDeadError is caught."""
        try:
            self.transition(RuntimeState.DEAD)
        except InvalidTransitionError as e:
            _log.debug(f"Could not transition to DEAD (already in {self._state.value}): {e}")
