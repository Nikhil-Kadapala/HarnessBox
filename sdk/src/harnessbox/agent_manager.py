"""Agent process management — lazy spawn and lifecycle control.

AgentManager handles ephemeral agent processes within a workspace. Agents are
spawned lazily when a prompt is sent to a conversation_id. Multiple agents can
run concurrently (git conflicts are user's responsibility).

Each agent is identified by conversation_id (Claude's session_id) and runs as
a AgentProcess with --resume {conversation_id} for conversation continuity.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, AsyncGenerator

from harnessbox.config.harness import get_harness_type
from harnessbox.process import AgentProcess
from harnessbox.streaming import StreamParser, UniversalEvent

if TYPE_CHECKING:
    from harnessbox.sandbox import Sandbox

logger = logging.getLogger(__name__)


class AgentManager:
    """Manages ephemeral agent processes within a workspace.

    Agents are spawned lazily when a prompt is sent to a conversation_id.
    Multiple agents can run concurrently (user's responsibility to handle git conflicts).
    """

    def __init__(self, sandbox: Sandbox) -> None:
        self._sandbox = sandbox
        self._agents: dict[str, AgentProcess] = {}  # conversation_id → process
        self._locks: dict[str, asyncio.Lock] = {}  # per-conversation lock

    async def run_prompt(
        self,
        conversation_id: str,
        prompt: str,
        harness: str = "claude-code",
    ) -> AsyncGenerator[UniversalEvent, None]:
        """Send prompt to conversation, spawn agent lazily if needed.

        Args:
            conversation_id: Claude's session_id for --resume
            prompt: User prompt
            harness: Agent type (claude-code, codex, etc.)
        """
        # Spawn agent if not running
        if conversation_id not in self._agents:
            await self._spawn_agent(conversation_id, harness)

        # Ensure lock exists
        if conversation_id not in self._locks:
            self._locks[conversation_id] = asyncio.Lock()

        # Send prompt
        async with self._locks[conversation_id]:
            process = self._agents[conversation_id]
            await process.send_prompt(prompt)

            async for event in process.stream_events():
                # Update conversation_id in event if not set
                if not event.session_id:
                    event.session_id = conversation_id

                yield event

    async def _spawn_agent(self, conversation_id: str, harness: str) -> None:
        """Spawn agent process with --resume {conversation_id}."""
        harness_config = get_harness_type(harness)

        cmd = harness_config.build_persistent_command(
            skip_permissions=self._sandbox._skip_permissions,
            session_id=conversation_id,  # Maps to --resume flag
        )

        parser = StreamParser(persistent=True)
        process = AgentProcess(self._sandbox._provider, parser)

        await process.start(cmd, cwd=self._sandbox._cwd)

        self._agents[conversation_id] = process
        self._locks[conversation_id] = asyncio.Lock()

        logger.info(f"Spawned agent for conversation {conversation_id}")

    def list_conversations(self) -> list[str]:
        """Return list of active conversation IDs."""
        return list(self._agents.keys())

    async def terminate_agent(self, conversation_id: str) -> None:
        """Stop and remove an agent process."""
        agent = self._agents.pop(conversation_id, None)
        if not agent:
            return

        if conversation_id in self._locks:
            async with self._locks[conversation_id]:
                await agent.stop()
        else:
            await agent.stop()

        self._locks.pop(conversation_id, None)
        logger.info(f"Terminated agent for conversation {conversation_id}")

    async def shutdown_all(self) -> None:
        """Terminate all agents."""
        for conversation_id in list(self._agents.keys()):
            await self.terminate_agent(conversation_id)
