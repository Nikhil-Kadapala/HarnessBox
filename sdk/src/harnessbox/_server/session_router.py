"""Session router — prompt routing, conversation resolution, and event persistence.

Handles the full prompt lifecycle: resolve/create conversation, upload attachments,
delegate to AgentManager, persist events to storage, and track turn boundaries.
"""

from __future__ import annotations

import base64
import logging
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from harnessbox.lifecycle import RuntimeState
from harnessbox.streaming import Attachment, ContentPart, UniversalEvent
from harnessbox.streaming import EventType as StreamEventType

if TYPE_CHECKING:
    from harnessbox._server.idle import IdleOrchestrator
    from harnessbox._server.registry import WorkspaceInstance, WorkspaceRegistry
    from harnessbox._server.storage import StorageBackend

logger = logging.getLogger(__name__)


class SessionRouter:
    """Routes prompts to the correct workspace/conversation and manages turn lifecycle."""

    def __init__(
        self,
        registry: WorkspaceRegistry,
        idle: IdleOrchestrator,
        storage: StorageBackend | None = None,
    ) -> None:
        self._registry = registry
        self._idle = idle
        self._storage = storage

    async def prompt(
        self,
        workspace_id: str,
        prompt: str,
        *,
        harness: str = "claude-code",
        conversation_id: str | None = None,
        attachments: list[Attachment] | None = None,
    ) -> AsyncGenerator[UniversalEvent, None]:
        """Send prompt to workspace, streaming events back.

        Ensures sandbox is connected, resolves conversation, uploads attachments,
        delegates to AgentManager, persists events, and manages turn lifecycle.
        """
        info = self._registry.get_workspace(workspace_id)

        await self._registry.ensure_sandbox(workspace_id)

        stored_agent_session_id: str | None = None
        conversation_id, stored_agent_session_id, harness = await self._resolve_conversation(
            workspace_id, conversation_id, harness
        )

        self._idle.turn_started(workspace_id)
        turn_ended_seen = False

        info.last_active = datetime.now(timezone.utc).isoformat()
        if self._storage:
            await self._storage.update_workspace(workspace_id, last_active=info.last_active)

        try:
            lock = self._registry._ensure_lock(workspace_id)
            async with lock:
                assert info.sandbox_conn is not None

                resolved_attachments = await self._upload_attachments(info, attachments or [])

                user_prompt_event = self._build_user_prompt_event(
                    prompt, conversation_id, resolved_attachments
                )
                if info.sandbox_conn._event_buffer:
                    user_prompt_event = await info.sandbox_conn._event_buffer.push(
                        user_prompt_event
                    )
                yield user_prompt_event
                if self._storage:
                    try:
                        await self._storage.append_events(
                            workspace_id, [user_prompt_event.to_dict()]
                        )
                    except Exception as e:
                        logger.error(f"Failed to persist user_prompt event: {e}")

                augmented_prompt = self._augment_prompt(prompt, resolved_attachments)

                conversation_saved = False
                agent_session_id: str | None = None
                async for event in info.agent_manager.send_message(
                    conversation_id,
                    augmented_prompt,
                    harness,
                    agent_session_id=stored_agent_session_id,
                ):
                    if (
                        event.event_type == "error"
                        and event.metadata.get("error_code") == "SANDBOX_DEAD"
                    ):
                        info.runtime_state = RuntimeState.DEAD.value

                    if event.cost_usd is not None:
                        info.total_cost_usd = event.cost_usd

                    _asi = event.metadata.get("_agent_session_id")
                    if _asi and not agent_session_id:
                        agent_session_id = _asi

                    if not conversation_saved and self._storage:
                        conversation_saved = True
                        try:
                            await self._storage.save_conversation(
                                {
                                    "conversation_id": conversation_id,
                                    "workspace_id": workspace_id,
                                    "agent_type": harness,
                                    "title": prompt[:50],
                                    "last_active": datetime.now(timezone.utc).isoformat(),
                                    "agent_session_id": agent_session_id,
                                }
                            )
                        except Exception as e:
                            logger.error(f"Failed to save conversation {conversation_id}: {e}")

                    yield event

                    if self._storage:
                        try:
                            await self._storage.append_events(workspace_id, [event.to_dict()])
                        except Exception as e:
                            logger.error(f"Failed to persist event {event.event_id}: {e}")

                    if event.event_type in (
                        StreamEventType.TURN_ENDED,
                        StreamEventType.SESSION_ENDED,
                    ):
                        turn_ended_seen = True
                        info.last_active = datetime.now(timezone.utc).isoformat()
                        if self._storage:
                            try:
                                await self._storage.update_workspace(
                                    workspace_id, last_active=info.last_active
                                )
                            except Exception as e:
                                logger.error(
                                    f"Failed to persist last_active for {workspace_id}: {e}"
                                )
                            if agent_session_id:
                                try:
                                    await self._storage.update_conversation(
                                        conversation_id,
                                        agent_session_id=agent_session_id,
                                    )
                                except Exception as e:
                                    logger.error(
                                        f"Failed to persist agent_session_id for "
                                        f"{conversation_id}: {e}"
                                    )
                        self._idle.turn_ended(workspace_id)
        finally:
            if not turn_ended_seen:
                self._idle.turn_errored(workspace_id, info.runtime_state)

    async def _resolve_conversation(
        self,
        workspace_id: str,
        conversation_id: str | None,
        harness: str,
    ) -> tuple[str, str | None, str]:
        """Resolve conversation_id, stored agent_session_id, and harness."""
        stored_agent_session_id: str | None = None

        if conversation_id is None:
            if self._storage:
                active_conv = await self._storage.get_active_conversation(workspace_id)
                if active_conv:
                    conversation_id = active_conv["conversation_id"]
                    stored_agent_session_id = active_conv.get("agent_session_id")
                    stored_harness = active_conv.get("agent_type")
                    if stored_harness:
                        harness = stored_harness
            if conversation_id is None:
                conversation_id = str(uuid.uuid4())
        elif self._storage:
            convs = await self._storage.get_conversations(workspace_id)
            for conv in convs:
                if conv["conversation_id"] == conversation_id:
                    stored_agent_session_id = conv.get("agent_session_id")
                    stored_harness = conv.get("agent_type")
                    if stored_harness:
                        harness = stored_harness
                    break

        return conversation_id, stored_agent_session_id, harness

    async def _upload_attachments(
        self, info: WorkspaceInstance, attachments: list[Attachment]
    ) -> list[Attachment]:
        """Write attachments to sandbox and return resolved copies with sandbox_path."""
        if not attachments:
            return []

        resolved: list[Attachment] = []
        assert info.sandbox_conn is not None
        cwd = info.sandbox_conn._cwd or "/workspace"

        for att in attachments:
            safe_name = Path(att.filename).name or "attachment"
            sandbox_path = f"{cwd}/.attachments/{att.attachment_id}/{safe_name}"
            await info.sandbox_conn._provider.make_dir(f"{cwd}/.attachments/{att.attachment_id}")
            raw_data = (
                base64.b64decode(att.data_b64 or "")
                if att.data_b64
                else (Path(att.storage_path).read_bytes() if att.storage_path else b"")
            )
            if raw_data:
                await info.sandbox_conn._provider.write_file(sandbox_path, raw_data)
            resolved.append(
                Attachment(
                    attachment_id=att.attachment_id,
                    filename=att.filename,
                    mime_type=att.mime_type,
                    size_bytes=att.size_bytes,
                    data_b64=att.data_b64,
                    storage_path=att.storage_path,
                    sandbox_path=sandbox_path,
                )
            )

        return resolved

    @staticmethod
    def _build_user_prompt_event(
        prompt: str,
        conversation_id: str,
        attachments: list[Attachment],
    ) -> UniversalEvent:
        """Build the USER_PROMPT event."""
        attachment_meta = [
            {
                "attachment_id": a.attachment_id,
                "filename": a.filename,
                "mime_type": a.mime_type,
                "size_bytes": a.size_bytes,
                "sandbox_path": a.sandbox_path,
                **({"data_b64": a.data_b64} if a.data_b64 and a.size_bytes < 1024 * 1024 else {}),
            }
            for a in attachments
        ]
        return UniversalEvent(
            event_id=str(uuid.uuid4()),
            sequence=0,
            timestamp=datetime.now(timezone.utc).isoformat(),
            session_id=conversation_id,
            event_type=StreamEventType.USER_PROMPT,
            content=(ContentPart(type="text", text=prompt),),
            metadata={
                "conversation_id": conversation_id,
                **({"attachments": attachment_meta} if attachment_meta else {}),
            },
        )

    @staticmethod
    def _augment_prompt(prompt: str, attachments: list[Attachment]) -> str:
        """Augment prompt with file references if attachments were uploaded."""
        if not attachments:
            return prompt
        file_list = "\n".join(f"- {a.sandbox_path}" for a in attachments)
        return f"{prompt}\n\n[Attached files written to sandbox:\n{file_list}]"
