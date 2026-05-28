"""Agent process management — lazy spawn and lifecycle control.

AgentManager maintains persistent agent processes per conversation_id within
a workspace. Each process accepts prompts via stdin JSON lines and streams
responses on stdout, staying alive across multiple turns for the same
conversation.

On snapshot recovery (process died but session_id is known), the process is
restarted with --resume <session_id> to restore Claude's conversation history.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from dataclasses import replace
from typing import TYPE_CHECKING

from harnessbox.config.harness import get_harness_type
from harnessbox.process import AgentProcess
from harnessbox.streaming import StreamParser, UniversalEvent

if TYPE_CHECKING:
    from harnessbox.sandbox import Sandbox

logger = logging.getLogger(__name__)


class AgentManager:
    """Maintains persistent agent processes per conversation_id within a workspace.

    Each conversation gets its own long-lived process, reused across turns.
    On recovery (process dead but agent_session_id known), spawns with --resume
    to restore conversation history.
    """

    def __init__(self, sandbox: Sandbox) -> None:
        self._sandbox = sandbox
        self._agents: dict[str, AgentProcess] = {}  # conversation_id → process
        self._locks: dict[str, asyncio.Lock] = {}  # per-conversation lock

    async def send_message(
        self,
        conversation_id: str,
        prompt: str,
        harness: str = "claude-code",
        *,
        agent_session_id: str | None = None,
    ) -> AsyncGenerator[UniversalEvent, None]:
        """Send prompt to the workspace's agent process, spawning if needed.

        Args:
            conversation_id: Stable conversation identifier (reused across turns)
            prompt: User prompt
            harness: Agent type (claude-code, codex, etc.)
            agent_session_id: Claude's session_id for --resume on recovery
        """
        if conversation_id not in self._agents:
            await self._spawn_agent(conversation_id, harness, agent_session_id=agent_session_id)

        if conversation_id not in self._locks:
            self._locks[conversation_id] = asyncio.Lock()

        async with self._locks[conversation_id]:
            process = self._agents[conversation_id]
            await process.send_prompt(prompt)

            captured_session_id = ""
            async for event in process.stream_turn():
                if event.session_id and event.session_id != conversation_id:
                    captured_session_id = event.session_id
                meta = {**event.metadata}
                if captured_session_id:
                    meta["_agent_session_id"] = captured_session_id
                event = replace(event, session_id=conversation_id, metadata=meta)
                event = await self._sandbox.event_buffer.push(event)
                yield event

            sid = captured_session_id or conversation_id
            for status_event in await process.poll_status(session_id=sid, timeout=10):
                status_event = await self._sandbox.event_buffer.push(status_event)
                yield status_event

    async def _spawn_agent(
        self,
        conversation_id: str,
        harness: str,
        *,
        agent_session_id: str | None = None,
    ) -> None:
        """Spawn agent process.

        If agent_session_id is provided (recovery from snapshot), uses --resume
        to restore Claude's conversation history. Otherwise starts fresh.
        """
        harness_config = get_harness_type(harness)

        cmd = harness_config.build_session_command(
            skip_permissions=self._sandbox._skip_permissions,
            model=self._sandbox._model,
            session_id=agent_session_id,
        )

        parser = StreamParser(persistent=True)
        process = AgentProcess(self._sandbox._provider, parser)

        await process.start(cmd, cwd=self._sandbox._cwd)

        self._agents[conversation_id] = process
        self._locks[conversation_id] = asyncio.Lock()

        logger.info(
            f"Spawned agent for conversation {conversation_id}"
            + (f" (resuming session {agent_session_id})" if agent_session_id else "")
        )

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
