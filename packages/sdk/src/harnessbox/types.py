"""Public data types for the HarnessBox SDK."""

from __future__ import annotations

from dataclasses import dataclass, field

from harnessbox.streaming import UniversalEvent


@dataclass(frozen=True)
class AgentResponse:
    """Accumulated response from a single agent turn.

    Returned by ``sandbox.send_message(input, stream=False)``.
    Contains the full text output, cost/timing metadata, and the
    raw event list for consumers that need finer granularity.
    """

    text: str
    cost_usd: float | None = None
    duration_ms: int | None = None
    session_id: str = ""
    events: list[UniversalEvent] = field(default_factory=list)
