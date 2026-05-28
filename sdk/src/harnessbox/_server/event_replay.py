"""Event replay — SSE reconnection from stored events.

Given a Last-Event-ID (sequence number), streams stored events that occurred
after that sequence, then hands off to the live EventBuffer for real-time events.
Used by the /events and /history server endpoints.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

from harnessbox.streaming import UniversalEvent

if TYPE_CHECKING:
    from harnessbox._server.storage import StorageBackend
    from harnessbox.events import EventBuffer

logger = logging.getLogger(__name__)


def _event_from_record(record: dict[str, Any]) -> UniversalEvent | None:
    """Reconstruct a UniversalEvent from a storage record dict."""
    try:
        event_json = record.get("event_json", "{}")
        data = json.loads(event_json) if isinstance(event_json, str) else event_json
        return UniversalEvent(
            event_id=data.get("event_id", record.get("event_id", "")),
            sequence=data.get("sequence", record.get("sequence", 0)),
            timestamp=data.get("timestamp", record.get("timestamp", "")),
            session_id=data.get("session_id", ""),
            event_type=data.get("event_type", record.get("event_type", "")),
            metadata=data.get("metadata", {}),
            delta=data.get("delta"),
            cost_usd=data.get("cost_usd"),
        )
    except Exception as e:
        logger.warning(f"Skipping malformed stored event: {e}")
        return None


class EventReplay:
    """Replays stored events for SSE reconnection then switches to live stream."""

    def __init__(self, storage: StorageBackend | None = None) -> None:
        self._storage = storage

    async def replay_from_sequence(
        self,
        workspace_id: str,
        after_sequence: int,
        *,
        limit: int = 1000,
    ) -> AsyncGenerator[UniversalEvent, None]:
        """Stream stored events with sequence > after_sequence."""
        if not self._storage:
            return

        try:
            async for event_record in self._storage.get_events(
                workspace_id, after_sequence=after_sequence, limit=limit
            ):
                event = _event_from_record(event_record)
                if event is not None:
                    yield event
        except Exception as e:
            logger.error(f"Failed to load events for replay (workspace={workspace_id}): {e}")

    async def replay_then_live(
        self,
        workspace_id: str,
        after_sequence: int,
        live_buffer: EventBuffer | None,
        *,
        replay_limit: int = 1000,
    ) -> AsyncGenerator[UniversalEvent, None]:
        """Replay stored events then seamlessly switch to live buffer.

        This is the primary method for SSE reconnection: replays everything
        the client missed, then subscribes to the live event buffer.
        """
        last_replayed_seq = after_sequence

        async for event in self.replay_from_sequence(
            workspace_id, after_sequence, limit=replay_limit
        ):
            last_replayed_seq = max(last_replayed_seq, event.sequence)
            yield event

        if live_buffer is None:
            return

        async for event in live_buffer.stream(last_replayed_seq):
            yield event

    async def get_history(
        self,
        workspace_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 500,
        conversation_id: str | None = None,
    ) -> AsyncGenerator[UniversalEvent, None]:
        """Stream historical events (for /history endpoint)."""
        if not self._storage:
            return

        try:
            async for event_record in self._storage.get_events(
                workspace_id,
                after_sequence=after_sequence,
                limit=limit,
            ):
                if conversation_id:
                    event_json = event_record.get("event_json", "{}")
                    data = json.loads(event_json) if isinstance(event_json, str) else event_json
                    if data.get("session_id") != conversation_id:
                        continue
                event = _event_from_record(event_record)
                if event is not None:
                    yield event
        except Exception as e:
            logger.error(f"Failed to load history for workspace {workspace_id}: {e}")
