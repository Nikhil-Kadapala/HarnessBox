"""Per-session event buffer with broadcast and replay.

Ported from Rivet Sandbox Agent's AdapterRuntime ring buffer + broadcast
pattern. Each session gets its own EventBuffer that stores recent events
in a bounded deque and fans out to async subscribers.

Reconnecting clients pass ``last_event_id`` (the sequence number of the
last event they received). The buffer replays missed events from the ring,
then streams live events — no gaps.

With storage enabled, events are batched and persisted (50 events or 5
seconds, whichever comes first). The ring buffer remains the source for
SSE replay — storage is for historical viewing only.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import deque
from collections.abc import AsyncGenerator
from dataclasses import asdict
from typing import TYPE_CHECKING

from harnessbox.streaming import UniversalEvent

if TYPE_CHECKING:
    from harnessbox.storage import StorageBackend

logger = logging.getLogger(__name__)


class EventBuffer:
    """Per-session event buffer with ring storage and fan-out broadcast.

    Thread-safe for use from a single asyncio event loop. Multiple
    subscribers can read concurrently; ``push()`` broadcasts to all.

    With storage enabled, events are batched and persisted in the background
    (50 events or 5 seconds). The ring buffer remains the source for SSE
    replay — storage is for historical viewing via GET /v1/sessions/{id}/history.
    """

    RING_SIZE = 1024
    BATCH_SIZE = 50
    BATCH_INTERVAL = 5.0

    def __init__(
        self,
        storage: StorageBackend | None = None,
        session_id: str = "",
    ) -> None:
        self._ring: deque[UniversalEvent] = deque(maxlen=self.RING_SIZE)
        self._subscribers: dict[str, asyncio.Queue[UniversalEvent | None]] = {}
        self._closed = False
        self._sequence = 0

        # Persistence
        self._storage = storage
        self._session_id = session_id
        self._pending: list[UniversalEvent] = []
        self._flush_task: asyncio.Task[None] | None = None

        # Start flush task if storage enabled
        if storage:
            self._flush_task = asyncio.create_task(self._run_flush_task())

    @property
    def size(self) -> int:
        """Return the number of events currently in the ring buffer."""
        return len(self._ring)

    @property
    def latest_sequence(self) -> int:
        """Return the sequence number of the most recent event, or 0 if empty."""
        return self._sequence

    async def push(self, event: UniversalEvent) -> None:
        """Push an event to the ring and broadcast to subscribers.

        Assigns a monotonically increasing sequence number, making EventBuffer
        the sole authority on event ordering regardless of source.

        If storage is enabled, the event is also queued for batched persistence.
        """
        self._sequence += 1
        event = UniversalEvent(
            event_id=event.event_id,
            sequence=self._sequence,
            timestamp=event.timestamp,
            session_id=event.session_id,
            event_type=event.event_type,
            item_id=event.item_id,
            item_kind=event.item_kind,
            item_status=event.item_status,
            content=event.content,
            delta=event.delta,
            tool_kind=event.tool_kind,
            cost_usd=event.cost_usd,
            duration_ms=event.duration_ms,
            error_message=event.error_message,
            metadata=event.metadata,
            raw=event.raw,
        )
        self._ring.append(event)

        # Broadcast to subscribers
        for queue in self._subscribers.values():
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

        # Queue for persistence
        if self._storage:
            self._pending.append(event)
            # Immediate flush if batch size reached
            if len(self._pending) >= self.BATCH_SIZE:
                await self._flush_events()

    def replay(self, after_sequence: int | None = None) -> list[UniversalEvent]:
        """Return events from the ring buffer after the given sequence number."""
        if after_sequence is None:
            return list(self._ring)
        return [e for e in self._ring if e.sequence > after_sequence]

    def subscribe(self, last_event_id: int | None = None) -> tuple[list[UniversalEvent], str]:
        """Start a subscription. Returns (replay_events, subscriber_id).

        The caller should read from the queue returned by ``get_queue()``.
        """
        sub_id = str(uuid.uuid4())
        self._subscribers[sub_id] = asyncio.Queue(maxsize=4096)
        replay = self.replay(last_event_id)
        return replay, sub_id

    def get_queue(self, subscriber_id: str) -> asyncio.Queue[UniversalEvent | None]:
        """Return the async queue for the given subscriber."""
        return self._subscribers[subscriber_id]

    def unsubscribe(self, subscriber_id: str) -> None:
        """Remove a subscriber and discard its queue."""
        self._subscribers.pop(subscriber_id, None)

    async def stream(
        self, last_event_id: int | None = None
    ) -> AsyncGenerator[UniversalEvent, None]:
        """Replay missed events then yield live events.

        This is the primary API for SSE consumers. Pass the sequence
        number of the last event the client received to avoid duplicates.
        """
        replay, sub_id = self.subscribe(last_event_id)
        queue = self.get_queue(sub_id)
        try:
            for event in replay:
                yield event

            while True:
                item: UniversalEvent | None = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            self.unsubscribe(sub_id)

    async def _flush_events(self) -> None:
        """Flush pending events to storage."""
        if not self._storage or not self._pending:
            return

        batch = self._pending[:]
        self._pending.clear()

        try:
            # Serialize events to storage format
            event_records = []
            for event in batch:
                event_dict = asdict(event)
                # Convert tuple to list for JSON serialization
                if "content" in event_dict and event_dict["content"]:
                    event_dict["content"] = [asdict(c) for c in event_dict["content"]]

                event_records.append(
                    {
                        "event_id": event.event_id,
                        "session_id": self._session_id,
                        "sequence": event.sequence,
                        "timestamp": event.timestamp,
                        "event_type": event.event_type.value,
                        "event_json": json.dumps(event_dict),
                    }
                )

            await self._storage.append_events(self._session_id, event_records)
        except Exception as e:
            logger.error(f"Failed to flush events for session {self._session_id}: {e}")

    async def _run_flush_task(self) -> None:
        """Background task: flush every BATCH_INTERVAL seconds."""
        try:
            while not self._closed:
                await asyncio.sleep(self.BATCH_INTERVAL)
                await self._flush_events()
        except asyncio.CancelledError:
            # Final flush on cancellation
            await self._flush_events()
            raise

    async def close(self) -> None:
        """Close buffer, flush remaining events, stop flush task."""
        self._closed = True

        # Cancel and wait for flush task
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        # Final flush
        await self._flush_events()

        # Broadcast close to subscribers
        for queue in self._subscribers.values():
            try:
                queue.put_nowait(None)
            except asyncio.QueueFull:
                pass
        self._subscribers.clear()
