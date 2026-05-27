"""Per-session event buffer with broadcast and replay.

Ported from Rivet Sandbox Agent's AdapterRuntime ring buffer + broadcast
pattern. Each session gets its own EventBuffer that stores recent events
in a bounded deque and fans out to async subscribers.

Reconnecting clients pass ``last_event_id`` (the sequence number of the
last event they received). The buffer replays missed events from the ring,
then streams live events — no gaps.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import deque
from collections.abc import AsyncGenerator

from harnessbox.streaming import (
    UniversalEvent,
)

logger = logging.getLogger(__name__)


class EventBuffer:
    """Per-session event buffer with ring storage and fan-out broadcast.

    Thread-safe for use from a single asyncio event loop. Multiple
    subscribers can read concurrently; ``push()`` broadcasts to all.
    """

    RING_SIZE = 1024

    def __init__(
        self,
        initial_sequence: int = 0,
    ) -> None:
        self._ring: deque[UniversalEvent] = deque(maxlen=self.RING_SIZE)
        self._subscribers: dict[str, asyncio.Queue[UniversalEvent | None]] = {}
        self._closed = False
        self._sequence = initial_sequence

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

        for queue in self._subscribers.values():
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

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

    async def close(self) -> None:
        """Signal all subscribers that the stream is closed."""
        self._closed = True

        for queue in self._subscribers.values():
            try:
                queue.put_nowait(None)
            except asyncio.QueueFull:
                pass
        self._subscribers.clear()
