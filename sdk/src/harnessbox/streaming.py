"""Universal event schema and stream parser for AI coding agent output.

Ported from Rivet Sandbox Agent's UniversalEvent schema (Rust) to Python.
Parses Claude Code's NDJSON ``--output-format stream-json`` into typed events
that map directly to UI components (text bubbles, tool cards, thinking blocks).

Create one ``StreamParser`` per agent session. It maintains state for tool_use_id
pairing and content block tracking across NDJSON lines.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

# ---------------------------------------------------------------------------
# Enums (ported from Sandbox Agent's universal_events.rs)
# ---------------------------------------------------------------------------


class EventType(str, Enum):
    """Types of universal stream events emitted during an agent session."""

    SESSION_STARTED = "session.started"
    SESSION_ENDED = "session.ended"
    TURN_STARTED = "turn.started"
    TURN_ENDED = "turn.ended"
    ITEM_STARTED = "item.started"
    ITEM_DELTA = "item.delta"
    ITEM_COMPLETED = "item.completed"
    ERROR = "error"
    PERMISSION_REQUESTED = "permission.requested"
    PERMISSION_RESOLVED = "permission.resolved"
    STATUS = "status"


class ItemKind(str, Enum):
    """Classification of stream items by their role in agent output."""

    MESSAGE = "message"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    REASONING = "reasoning"
    STATUS = "status"


class ItemStatus(str, Enum):
    """Lifecycle status of a stream item."""

    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class ToolKind(str, Enum):
    """Category of tool invoked by the agent."""

    BASH = "bash"
    FILE_CHANGE = "file_change"
    FILE_READ = "file_read"
    WEB = "web"
    AGENT = "agent"
    OTHER = "other"


_TOOL_KIND_MAP: dict[str, ToolKind] = {
    "Bash": ToolKind.BASH,
    "Shell": ToolKind.BASH,
    "Write": ToolKind.FILE_CHANGE,
    "Edit": ToolKind.FILE_CHANGE,
    "MultiEdit": ToolKind.FILE_CHANGE,
    "NotebookEdit": ToolKind.FILE_CHANGE,
    "Read": ToolKind.FILE_READ,
    "Glob": ToolKind.FILE_READ,
    "Grep": ToolKind.FILE_READ,
    "WebSearch": ToolKind.WEB,
    "WebFetch": ToolKind.WEB,
    "Agent": ToolKind.AGENT,
}


def classify_tool(name: str) -> ToolKind:
    """Map a tool name to its ToolKind category."""
    return _TOOL_KIND_MAP.get(name, ToolKind.OTHER)


# ---------------------------------------------------------------------------
# Content part (maps to Sandbox Agent's ContentPart tagged union)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContentPart:
    """A single content fragment within a UniversalEvent (text, tool call, file ref)."""

    type: str
    text: str | None = None
    tool_name: str | None = None
    tool_input: str | None = None
    call_id: str | None = None
    file_path: str | None = None
    file_action: str | None = None


# ---------------------------------------------------------------------------
# Universal event
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UniversalEvent:
    """A single event in a sandbox agent session stream.

    Modeled after Sandbox Agent's ``UniversalEvent`` schema.
    Every event gets a monotonic sequence number for SSE replay.
    """

    event_id: str
    sequence: int
    timestamp: str
    session_id: str
    event_type: EventType
    item_id: str | None = None
    item_kind: ItemKind | None = None
    item_status: ItemStatus | None = None
    content: tuple[ContentPart, ...] = ()
    delta: str | None = None
    tool_kind: ToolKind | None = None
    cost_usd: float | None = None
    duration_ms: int | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize the event to a JSON-compatible dictionary."""
        d: dict[str, Any] = {
            "event_id": self.event_id,
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "event_type": self.event_type.value,
        }
        if self.item_id is not None:
            d["item_id"] = self.item_id
        if self.item_kind is not None:
            d["item_kind"] = self.item_kind.value
        if self.item_status is not None:
            d["item_status"] = self.item_status.value
        if self.content:
            d["content"] = [
                {k: v for k, v in c.__dict__.items() if v is not None} for c in self.content
            ]
        if self.delta is not None:
            d["delta"] = self.delta
        if self.tool_kind is not None:
            d["tool_kind"] = self.tool_kind.value
        if self.cost_usd is not None:
            d["cost_usd"] = self.cost_usd
        if self.duration_ms is not None:
            d["duration_ms"] = self.duration_ms
        if self.error_message is not None:
            d["error_message"] = self.error_message
        if self.metadata:
            d["metadata"] = self.metadata
        return d


# Backward-compatible aliases
AgentStreamEvent = UniversalEvent
StreamEventType = EventType


# ---------------------------------------------------------------------------
# Stream parser — Claude Code NDJSON → UniversalEvent
# ---------------------------------------------------------------------------


@dataclass
class _ToolInfo:
    name: str
    input_buffer: str = ""


class StreamParser:
    """Stateful parser converting Claude Code stream-json NDJSON to UniversalEvents.

    Tracks active content blocks, tool_use_id → tool_result pairing, and
    session_id across the stream. Create one per agent session.
    """

    def __init__(self, session_id: str = "", *, persistent: bool = False) -> None:
        self._session_id = session_id
        self._sequence = 0
        self._tool_map: dict[str, _ToolInfo] = {}
        self._active_blocks: dict[int, dict[str, Any]] = {}
        self._turn_active = False
        self._persistent = persistent
        self._turn_count = 0

    @property
    def session_id(self) -> str:
        """Return the session ID discovered from the stream."""
        return self._session_id

    def parse(self, line: str) -> UniversalEvent | None:
        """Parse a line and return the first event, or None.

        For lines that produce multiple events (e.g., ``result`` with
        permission denials), only the first event is returned. Use
        ``parse_line()`` to get all events from a single line.
        """
        events = self.parse_line(line)
        return events[0] if events else None

    def _parse_all(self, data: dict[str, Any]) -> list[UniversalEvent]:
        msg_type = data.get("type")

        if msg_type == "system":
            e = self._parse_system(data)
            return [e] if e else []
        if msg_type == "stream_event":
            e = self._parse_stream_event(data)
            return [e] if e else []
        if msg_type == "assistant":
            e = self._parse_assistant(data)
            return [e] if e else []
        if msg_type == "user":
            return self._parse_user(data) or []
        if msg_type == "result":
            r = self._parse_result(data)
            return r if isinstance(r, list) else [r]
        if msg_type == "control_request":
            return self._parse_control_request(data)
        if msg_type == "_process_error":
            return [
                self._make_event(
                    EventType.ERROR,
                    error_message=data.get("stderr", "process error"),
                    raw=data,
                )
            ]
        return []

    # -- system.init -------------------------------------------------------

    def _parse_system(self, data: dict[str, Any]) -> UniversalEvent | None:
        if data.get("subtype") != "init":
            return None
        sid = data.get("session_id", "")
        if sid:
            self._session_id = sid
        self._turn_count += 1
        tools = data.get("tools", [])
        event_type = (
            EventType.TURN_STARTED
            if self._persistent and self._turn_count > 1
            else EventType.SESSION_STARTED
        )
        return self._make_event(
            event_type,
            metadata={"tools": tools, "turn": self._turn_count},
            raw=data,
        )

    # -- stream_event (content_block_start/delta/stop, message_stop) -------

    def _parse_stream_event(self, data: dict[str, Any]) -> UniversalEvent | None:
        event = data.get("event", {})
        se_type = event.get("type", "")

        if se_type == "content_block_start":
            return self._on_block_start(event, data)
        if se_type == "content_block_delta":
            return self._on_block_delta(event, data)
        if se_type == "content_block_stop":
            return self._on_block_stop(event, data)
        if se_type == "message_stop":
            self._turn_active = False
            self._active_blocks.clear()
            return self._make_event(EventType.TURN_ENDED, raw=data)
        return None

    def _on_block_start(self, event: dict[str, Any], raw: dict[str, Any]) -> UniversalEvent | None:
        block = event.get("content_block", {})
        block_type = block.get("type", "")
        index = event.get("index", 0)
        self._active_blocks[index] = {"type": block_type, "id": block.get("id")}

        if not self._turn_active:
            self._turn_active = True

        if block_type == "thinking":
            item_id = str(uuid.uuid4())
            self._active_blocks[index]["item_id"] = item_id
            return self._make_event(
                EventType.ITEM_STARTED,
                item_id=item_id,
                item_kind=ItemKind.REASONING,
                item_status=ItemStatus.IN_PROGRESS,
                raw=raw,
            )

        if block_type == "text":
            item_id = str(uuid.uuid4())
            self._active_blocks[index]["item_id"] = item_id
            return self._make_event(
                EventType.ITEM_STARTED,
                item_id=item_id,
                item_kind=ItemKind.MESSAGE,
                item_status=ItemStatus.IN_PROGRESS,
                raw=raw,
            )

        if block_type == "tool_use":
            tool_name = block.get("name", "")
            call_id = block.get("id", "")
            item_id = call_id or str(uuid.uuid4())
            self._active_blocks[index]["item_id"] = item_id
            self._tool_map[call_id] = _ToolInfo(name=tool_name)
            return self._make_event(
                EventType.ITEM_STARTED,
                item_id=item_id,
                item_kind=ItemKind.TOOL_CALL,
                item_status=ItemStatus.IN_PROGRESS,
                tool_kind=classify_tool(tool_name),
                content=(ContentPart(type="tool_call", tool_name=tool_name, call_id=call_id),),
                raw=raw,
            )
        return None

    def _on_block_delta(self, event: dict[str, Any], raw: dict[str, Any]) -> UniversalEvent | None:
        delta = event.get("delta", {})
        delta_type = delta.get("type", "")
        index = event.get("index", 0)
        block_info = self._active_blocks.get(index, {})
        item_id = block_info.get("item_id")

        if delta_type == "text_delta":
            text = delta.get("text", "")
            return self._make_event(
                EventType.ITEM_DELTA,
                item_id=item_id,
                item_kind=ItemKind.MESSAGE,
                delta=text,
                raw=raw,
            )

        if delta_type == "thinking_delta":
            text = delta.get("thinking", "")
            return self._make_event(
                EventType.ITEM_DELTA,
                item_id=item_id,
                item_kind=ItemKind.REASONING,
                delta=text,
                raw=raw,
            )

        if delta_type == "input_json_delta":
            chunk = delta.get("partial_json", "")
            call_id = block_info.get("id", "")
            if call_id and call_id in self._tool_map:
                self._tool_map[call_id].input_buffer += chunk
            tool_name = self._tool_map.get(call_id, _ToolInfo("")).name if call_id else None
            return self._make_event(
                EventType.ITEM_DELTA,
                item_id=item_id,
                item_kind=ItemKind.TOOL_CALL,
                delta=chunk,
                tool_kind=classify_tool(tool_name) if tool_name else None,
                raw=raw,
            )
        return None

    def _on_block_stop(self, event: dict[str, Any], raw: dict[str, Any]) -> UniversalEvent | None:
        index = event.get("index", 0)
        block_info = self._active_blocks.pop(index, {})
        block_type = block_info.get("type", "")
        item_id = block_info.get("item_id")

        if block_type == "tool_use":
            call_id = block_info.get("id", "")
            tool_info = self._tool_map.get(call_id)
            tool_name = tool_info.name if tool_info else None
            return self._make_event(
                EventType.ITEM_COMPLETED,
                item_id=item_id,
                item_kind=ItemKind.TOOL_CALL,
                item_status=ItemStatus.COMPLETED,
                tool_kind=classify_tool(tool_name) if tool_name else None,
                raw=raw,
            )

        if block_type == "thinking":
            return self._make_event(
                EventType.ITEM_COMPLETED,
                item_id=item_id,
                item_kind=ItemKind.REASONING,
                item_status=ItemStatus.COMPLETED,
                raw=raw,
            )

        if block_type == "text":
            return self._make_event(
                EventType.ITEM_COMPLETED,
                item_id=item_id,
                item_kind=ItemKind.MESSAGE,
                item_status=ItemStatus.COMPLETED,
                raw=raw,
            )
        return None

    # -- assistant message (full turn with tool_use blocks) ----------------

    def _parse_assistant(self, data: dict[str, Any]) -> UniversalEvent | None:
        message = data.get("message", {})
        sid = data.get("session_id") or message.get("session_id")
        if sid:
            self._session_id = sid

        for block in message.get("content", []):
            if block.get("type") == "tool_use":
                call_id = block.get("id", "")
                name = block.get("name", "")
                self._tool_map[call_id] = _ToolInfo(
                    name=name,
                    input_buffer=json.dumps(block.get("input", {})),
                )

        text_parts = [
            block.get("text", "")
            for block in message.get("content", [])
            if block.get("type") == "text"
        ]
        return self._make_event(
            EventType.TURN_ENDED,
            metadata={"text": "\n".join(text_parts)} if text_parts else {},
            raw=data,
        )

    # -- user message (tool_result blocks) ---------------------------------

    def _parse_user(self, data: dict[str, Any]) -> list[UniversalEvent] | None:
        message = data.get("message", {})
        content = message.get("content", [])
        if not isinstance(content, list):
            return None
        events: list[UniversalEvent] = []

        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            call_id = block.get("tool_use_id", "")
            tool_info = self._tool_map.get(call_id)
            tool_name = tool_info.name if tool_info else "unknown"
            is_error = block.get("is_error", False)
            output_parts = block.get("content", "")
            if isinstance(output_parts, list):
                output = "".join(c.get("text", "") for c in output_parts)
            else:
                output = str(output_parts)

            tool_input = ""
            if tool_info:
                try:
                    parsed = json.loads(tool_info.input_buffer)
                    tool_input = tool_info.input_buffer
                except (json.JSONDecodeError, ValueError):
                    parsed = {}
                    tool_input = tool_info.input_buffer
            else:
                parsed = {}

            tk = classify_tool(tool_name)
            content_parts: list[ContentPart] = []

            if tk == ToolKind.BASH:
                content_parts.append(
                    ContentPart(
                        type="tool_result",
                        tool_name=tool_name,
                        call_id=call_id,
                        text=output,
                        tool_input=parsed.get("command", ""),
                    )
                )
            elif tk == ToolKind.FILE_CHANGE:
                content_parts.append(
                    ContentPart(
                        type="file_ref",
                        tool_name=tool_name,
                        call_id=call_id,
                        file_path=parsed.get("file_path", parsed.get("path", "")),
                        file_action="write" if tool_name == "Write" else "patch",
                    )
                )
            elif tk == ToolKind.FILE_READ:
                content_parts.append(
                    ContentPart(
                        type="file_ref",
                        tool_name=tool_name,
                        call_id=call_id,
                        file_path=parsed.get(
                            "file_path", parsed.get("path", parsed.get("pattern", ""))
                        ),
                        file_action="read",
                    )
                )
            else:
                content_parts.append(
                    ContentPart(
                        type="tool_result",
                        tool_name=tool_name,
                        call_id=call_id,
                        text=output,
                        tool_input=tool_input,
                    )
                )

            events.append(
                self._make_event(
                    EventType.ITEM_COMPLETED,
                    item_id=call_id,
                    item_kind=ItemKind.TOOL_RESULT,
                    item_status=ItemStatus.FAILED if is_error else ItemStatus.COMPLETED,
                    tool_kind=tk,
                    content=tuple(content_parts),
                    raw=data,
                )
            )

        return events if events else None

    # -- result (final) ----------------------------------------------------

    def _parse_result(self, data: dict[str, Any]) -> UniversalEvent | list[UniversalEvent]:
        import logging
        logger = logging.getLogger("harnessbox.streaming")

        sid = data.get("session_id")
        if sid:
            self._session_id = sid

        is_error = data.get("is_error", False)
        if is_error:
            logger.error("Claude agent error - result data: %s", data)

        events: list[UniversalEvent] = []

        for denial in (
            data.get("result", {}).get("permission_denials", [])
            if isinstance(data.get("result"), dict)
            else []
        ):
            events.append(
                self._make_event(
                    EventType.PERMISSION_REQUESTED,
                    metadata={"tool": denial.get("tool_name", "")},
                    raw=data,
                )
            )

        result_text = data.get("result", "")
        if isinstance(result_text, dict):
            result_text = result_text.get("text", str(result_text))

        event_type = EventType.TURN_ENDED if self._persistent else EventType.SESSION_ENDED
        events.append(
            self._make_event(
                event_type,
                cost_usd=data.get("total_cost_usd"),
                duration_ms=data.get("duration_ms"),
                error_message=str(result_text) if is_error else None,
                metadata={
                    "is_error": is_error,
                    "result": str(result_text) if not is_error else None,
                    "turn": self._turn_count,
                },
                raw=data,
            )
        )
        return events if len(events) > 1 else events[0]

    # -- control_request (permission gate from persistent process) ----------

    def _parse_control_request(self, data: dict[str, Any]) -> list[UniversalEvent]:
        request = data.get("request", {})
        return [
            self._make_event(
                EventType.PERMISSION_REQUESTED,
                metadata={
                    "request_id": data.get("request_id"),
                    "subtype": request.get("subtype"),
                    "tool_name": request.get("tool_name"),
                    "tool_input": request.get("input"),
                },
                raw=data,
            )
        ]

    # -- event factory -----------------------------------------------------

    def _next_seq(self) -> int:
        self._sequence += 1
        return self._sequence

    def _make_event(
        self,
        event_type: EventType,
        *,
        item_id: str | None = None,
        item_kind: ItemKind | None = None,
        item_status: ItemStatus | None = None,
        content: tuple[ContentPart, ...] = (),
        delta: str | None = None,
        tool_kind: ToolKind | None = None,
        cost_usd: float | None = None,
        duration_ms: int | None = None,
        error_message: str | None = None,
        metadata: dict[str, Any] | None = None,
        raw: dict[str, Any] | None = None,
    ) -> UniversalEvent:
        return UniversalEvent(
            event_id=str(uuid.uuid4()),
            sequence=self._next_seq(),
            timestamp=datetime.now(timezone.utc).isoformat(),
            session_id=self._session_id,
            event_type=event_type,
            item_id=item_id,
            item_kind=item_kind,
            item_status=item_status,
            content=content,
            delta=delta,
            tool_kind=tool_kind,
            cost_usd=cost_usd,
            duration_ms=duration_ms,
            error_message=error_message,
            metadata=metadata or {},
            raw=raw,
        )

    # -- multi-event parse wrapper -----------------------------------------

    def parse_line(self, line: str) -> list[UniversalEvent]:
        """Parse a line and return zero or more events.

        Unlike ``parse()`` which returns a single event or None,
        this handles the cases where one NDJSON line produces
        multiple events (e.g., ``user`` with multiple tool_results,
        or ``result`` with permission_denials + session_ended).
        """
        line = line.strip()
        if not line:
            return []
        try:
            data = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            return []
        if not isinstance(data, dict):
            return []
        return self._parse_all(data)


def parse_stream_line(line: str) -> UniversalEvent | None:
    """Stateless convenience for parsing a single stream-json line.

    Returns the first event if the line produces multiple events,
    or None if the line is unparseable.
    """
    parser = StreamParser()
    events = parser.parse_line(line)
    return events[0] if events else None
