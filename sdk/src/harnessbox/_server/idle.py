"""Idle orchestrator — per-workspace timer management and auto-pause.

Tracks active turns per workspace and manages countdown tasks that fire
auto-pause after a configurable timeout of inactivity.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Callable, Coroutine

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class IdleOrchestrator:
    """Manages per-workspace idle timers and active-turn counting.

    The idle timer only restarts when ALL concurrent turns for a workspace
    have completed, preventing auto-pause while any conversation is active.
    """

    def __init__(
        self,
        pause_timeout: int = 1800,
        auto_pause: bool = True,
        pause_callback: Callable[[str], Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        self._pause_timeout = pause_timeout
        self._auto_pause = auto_pause
        self._pause_callback = pause_callback
        self._idle_timers: dict[str, asyncio.Task[None]] = {}
        self._active_turns: dict[str, int] = {}

    @property
    def auto_pause(self) -> bool:
        return self._auto_pause

    def start_timer(self, workspace_id: str) -> None:
        """Start (or restart) the per-workspace idle countdown."""
        if not self._auto_pause:
            return
        self.cancel_timer(workspace_id)
        self._idle_timers[workspace_id] = asyncio.create_task(self._idle_countdown(workspace_id))

    def cancel_timer(self, workspace_id: str) -> None:
        """Cancel the per-workspace idle task if running."""
        task = self._idle_timers.pop(workspace_id, None)
        if task and not task.done():
            task.cancel()

    def cancel_all(self) -> None:
        """Cancel all idle timers (for shutdown)."""
        for wid in list(self._idle_timers):
            self.cancel_timer(wid)

    def turn_started(self, workspace_id: str) -> None:
        """Record that a turn has started — cancels idle countdown."""
        self.cancel_timer(workspace_id)
        self._active_turns[workspace_id] = self._active_turns.get(workspace_id, 0) + 1

    def turn_ended(self, workspace_id: str) -> None:
        """Record that a turn has ended — restarts idle timer if no turns remain."""
        active = max(0, self._active_turns.get(workspace_id, 1) - 1)
        self._active_turns[workspace_id] = active
        if active == 0 and self._auto_pause:
            self.start_timer(workspace_id)

    def turn_errored(self, workspace_id: str, runtime_state: str) -> None:
        """Record that a turn errored before completing — restarts idle if appropriate."""
        active = max(0, self._active_turns.get(workspace_id, 1) - 1)
        self._active_turns[workspace_id] = active
        if active == 0 and self._auto_pause and runtime_state == "active":
            self.start_timer(workspace_id)

    def remove_workspace(self, workspace_id: str) -> None:
        """Clean up all state for a destroyed workspace."""
        self.cancel_timer(workspace_id)
        self._active_turns.pop(workspace_id, None)

    async def _idle_countdown(self, workspace_id: str) -> None:
        """Sleep for pause_timeout then invoke the pause callback."""
        try:
            await asyncio.sleep(self._pause_timeout)
        except asyncio.CancelledError:
            return
        if self._pause_callback:
            try:
                await self._pause_callback(workspace_id)
            except Exception as e:
                logger.error(f"Auto-pause failed for {workspace_id}: {e}")
