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
from typing import TYPE_CHECKING, Any

from harnessbox.streaming import (
    ContentPart,
    EventType,
    ItemKind,
    ItemStatus,
    ToolKind,
    UniversalEvent,
)

if TYPE_CHECKING:
    from harnessbox.storage import StorageBackend

logger = logging.getLogger(__name__)


def deserialize_event(data: dict[str, Any]) -> UniversalEvent:
    """Rebuild a UniversalEvent from a stored JSON dict.

    The dict is expected to match the output of ``UniversalEvent.to_dict()``
    (top-level keys: type, timestamp, message).
    """
    msg = data.get("message", {})
    content_parts: tuple[ContentPart, ...] = ()
    raw_content = msg.get("content")
    if raw_content and isinstance(raw_content, list):
        content_parts = tuple(ContentPart(**part) for part in raw_content)

    return UniversalEvent(
        event_id=msg.get("event_id", ""),
        sequence=msg.get("sequence", 0),
        timestamp=data.get("timestamp", ""),
        session_id=msg.get("session_id", ""),
        event_type=EventType(data["type"]),
        item_id=msg.get("item_id"),
        item_kind=ItemKind(msg["item_kind"]) if msg.get("item_kind") else None,
        item_status=ItemStatus(msg["item_status"]) if msg.get("item_status") else None,
        content=content_parts,
        delta=msg.get("delta"),
        tool_kind=ToolKind(msg["tool_kind"]) if msg.get("tool_kind") else None,
        cost_usd=msg.get("cost_usd"),
        duration_ms=msg.get("duration_ms"),
        error_message=msg.get("error_message"),
        metadata=msg.get("metadata", {}),
    )


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
        initial_sequence: int = 0,
    ) -> None:
        self._ring: deque[UniversalEvent] = deque(maxlen=self.RING_SIZE)
        self._subscribers: dict[str, asyncio.Queue[UniversalEvent | None]] = {}
        self._closed = False
        self._sequence = initial_sequence

        # Persistence
        self._storage = storage
        self._session_id = session_id
        self._pending: list[UniversalEvent] = []
        self._flush_lock = asyncio.Lock()
        self._flush_task: asyncio.Task[None] | None = None

        # Cross-batch delta accumulator for storage compaction
        self._delta_acc: dict[str, str] = {}

        # Start flush task if storage enabled
        if storage:
            self._flush_task = asyncio.create_task(self._run_flush_task())

    @property
    def size(self) -> int:
        """Return the number of events currently in the ring buffer."""
        return len(self._ring)

    @property
    def latest_sequence(self) -> int:
        """Return the sequence number of the most recent event.

        When constructed with ``initial_sequence``, this reflects the continuation
        point even before new events arrive (enables gapless timeline on reconnect).
        """
        return self._sequence

    async def push(self, event: UniversalEvent) -> UniversalEvent:
        """Push an event to the ring and broadcast to subscribers.

        Assigns a monotonically increasing sequence number, making EventBuffer
        the sole authority on event ordering regardless of source.

        If storage is enabled, the event is also queued for batched persistence.

        Returns:
            The event with its authoritative sequence number assigned.
            Callers must yield/use this returned event (not the original)
            to ensure SSE streams carry correct sequence IDs.
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

        return event

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

    def _compact_batch(self, batch: list[UniversalEvent]) -> list[UniversalEvent]:
        """Compact a batch for storage: collapse item.delta runs into item.completed.

        Live SSE streaming still gets individual deltas from the ring buffer.
        Storage only keeps the consolidated items for efficient replay.

        Uses self._delta_acc to carry incomplete items across batch boundaries
        (e.g., deltas in batch N, item.completed in batch N+1).
        """
        compacted: list[UniversalEvent] = []

        for event in batch:
            if event.event_type == EventType.ITEM_DELTA and event.item_id:
                self._delta_acc[event.item_id] = self._delta_acc.get(event.item_id, "") + (
                    event.delta or ""
                )
                continue

            if event.event_type == EventType.ITEM_COMPLETED and event.item_id:
                full_text = self._delta_acc.pop(event.item_id, None)
                if full_text:
                    event = UniversalEvent(
                        event_id=event.event_id,
                        sequence=event.sequence,
                        timestamp=event.timestamp,
                        session_id=event.session_id,
                        event_type=event.event_type,
                        item_id=event.item_id,
                        item_kind=event.item_kind,
                        item_status=event.item_status,
                        content=(ContentPart(type="text", text=full_text),),
                        delta=None,
                        tool_kind=event.tool_kind,
                        cost_usd=event.cost_usd,
                        duration_ms=event.duration_ms,
                        error_message=event.error_message,
                        metadata=event.metadata,
                    )

            compacted.append(event)

        return compacted

    async def _flush_events(self) -> None:
        """Flush pending events to storage (compacted).

        Uses a lock to prevent concurrent flushes and swaps _pending atomically
        so events arriving during the await are not lost.

        Before writing, compacts item.delta runs into enriched item.completed
        events. Live SSE still streams individual deltas from the ring buffer.
        """
        if not self._storage or not self._pending:
            return

        async with self._flush_lock:
            if not self._pending:
                return

            # Swap atomically: new events during await go into fresh list
            batch = self._pending
            self._pending = []

            try:
                compacted = self._compact_batch(batch)
                event_records = []
                for event in compacted:
                    event_dict = event.to_dict()
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
                # Re-queue failed batch at the front so they retry next flush
                self._pending = batch + self._pending
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

        # Drain any orphaned deltas (process crashed before item.completed)
        if self._delta_acc and self._storage:
            from datetime import datetime, timezone

            now = datetime.now(timezone.utc).isoformat()
            for item_id, text in self._delta_acc.items():
                self._pending.append(
                    UniversalEvent(
                        event_id=str(uuid.uuid4()),
                        sequence=self._sequence,
                        timestamp=now,
                        session_id=self._session_id,
                        event_type=EventType.ITEM_COMPLETED,
                        item_id=item_id,
                        item_kind=ItemKind.MESSAGE,
                        item_status=ItemStatus.COMPLETED,
                        content=(ContentPart(type="text", text=text),),
                    )
                )
            self._delta_acc.clear()

        # Final flush
        await self._flush_events()

        # Broadcast close to subscribers
        for queue in self._subscribers.values():
            try:
                queue.put_nowait(None)
            except asyncio.QueueFull:
                pass
        self._subscribers.clear()

    async def hydrate(self) -> None:
        """Load recent events from storage into the ring buffer.

        Called on reconnect to fill the in-memory ring so that SSE clients
        resuming with a Last-Event-ID can replay without gaps. Also updates
        the internal sequence counter to the maximum stored sequence.

        No-op if storage is not configured or session_id is empty.
        """
        if not self._storage or not self._session_id:
            return

        events_loaded = 0
        async for record in self._storage.get_events(
            self._session_id, after_sequence=0, limit=self.RING_SIZE
        ):
            event_json = record.get("event_json", "")
            try:
                event_data = json.loads(event_json) if isinstance(event_json, str) else event_json
                event = deserialize_event(event_data)
                self._ring.append(event)
                if event.sequence > self._sequence:
                    self._sequence = event.sequence
                events_loaded += 1
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.warning(f"Skipping malformed event during hydration: {e}")

        if events_loaded:
            logger.info(
                f"Hydrated {events_loaded} events for session {self._session_id}, "
                f"sequence at {self._sequence}"
            )
