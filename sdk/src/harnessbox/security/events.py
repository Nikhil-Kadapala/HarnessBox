"""Event system for sandbox session observability."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class EventType(str, Enum):
    """Types of events emitted during a sandbox session."""

    SETUP_COMPLETE = "setup_complete"
    SESSION_END = "session_end"
    COMMAND_RUN = "command_run"
    STATE_CHANGED = "state_changed"


@dataclass(frozen=True)
class SandboxEvent:
    """A structured record of something that happened in a sandbox session."""

    timestamp: str
    sandbox_id: str | None
    event_type: EventType
    action: str
    resource: str | None = None
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class EventHandler(Protocol):
    """Protocol for receiving sandbox events."""

    async def handle(self, event: SandboxEvent) -> None: ...


class JsonLogger:
    """Prints each event as a JSON line to stdout."""

    async def handle(self, event: SandboxEvent) -> None:
        data = asdict(event)
        data["event_type"] = event.event_type.value
        print(json.dumps(data, default=str), file=sys.stdout, flush=True)


class CallbackHandler:
    """Calls a user-provided callable for each event."""

    def __init__(self, callback: Callable[[SandboxEvent], Any]) -> None:
        self._callback = callback

    async def handle(self, event: SandboxEvent) -> None:
        result = self._callback(event)
        if hasattr(result, "__await__"):
            await result
