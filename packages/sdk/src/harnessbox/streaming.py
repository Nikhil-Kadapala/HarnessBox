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
from dataclasses import dataclass, field, replace
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
    API_RETRY = "api.retry"
    INPUT_REQUESTED = "input.requested"
    CONTEXT_UPDATE = "context.update"
    COST_UPDATE = "cost.update"
    USER_PROMPT = "user.prompt"
    RUNTIME_STATE = "runtime.state"


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


@dataclass(frozen=True)
class Attachment:
    """A file or image attached to a user prompt."""

    attachment_id: str
    filename: str
    mime_type: str
    size_bytes: int
    data_b64: str | None = None
    storage_path: str | None = None
    sandbox_path: str | None = None


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
        msg: dict[str, Any] = {
            "event_id": self.event_id,
            "sequence": self.sequence,
            "session_id": self.session_id,
        }
        if self.item_id is not None:
            msg["item_id"] = self.item_id
        if self.item_kind is not None:
            msg["item_kind"] = self.item_kind.value
        if self.item_status is not None:
            msg["item_status"] = self.item_status.value
        if self.content:
            msg["content"] = [
                {k: v for k, v in c.__dict__.items() if v is not None} for c in self.content
            ]
        if self.delta is not None:
            msg["delta"] = self.delta
        if self.tool_kind is not None:
            msg["tool_kind"] = self.tool_kind.value
        if self.cost_usd is not None:
            msg["cost_usd"] = self.cost_usd
        if self.duration_ms is not None:
            msg["duration_ms"] = self.duration_ms
        if self.error_message is not None:
            msg["error_message"] = self.error_message
        if self.metadata:
            msg["metadata"] = self.metadata
        return {
            "type": self.event_type.value,
            "timestamp": self.timestamp,
            "message": msg,
        }

    def to_storage_dict(self) -> dict[str, Any]:
        """Serialize to the flat row shape StorageBackend.append_events() expects.

        Distinct from to_dict(), which nests fields under "message" for the SSE
        wire format — storage backends key rows on top-level event_id/sequence/
        timestamp/event_type and store the rest as a flat JSON blob in
        event_json (see EventReplay._event_from_record, the read-side inverse,
        which expects top-level event_type/session_id/metadata/delta/cost_usd
        inside that blob rather than nested under "message").
        """
        payload: dict[str, Any] = {
            "event_id": self.event_id,
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "event_type": self.event_type.value,
            "item_id": self.item_id,
            "item_kind": self.item_kind.value if self.item_kind else None,
            "item_status": self.item_status.value if self.item_status else None,
            "content": [
                {k: v for k, v in c.__dict__.items() if v is not None} for c in self.content
            ],
            "delta": self.delta,
            "tool_kind": self.tool_kind.value if self.tool_kind else None,
            "cost_usd": self.cost_usd,
            "duration_ms": self.duration_ms,
            "error_message": self.error_message,
            "metadata": self.metadata,
        }
        return {
            "event_id": self.event_id,
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "event_type": self.event_type.value,
            "event_json": json.dumps(payload),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UniversalEvent":
        """Reconstruct from a to_dict() payload.

        Inverse of to_dict(). Handles enum coercion for EventType, ItemKind,
        ItemStatus, and ToolKind. content parts are reconstructed from the
        serialized dicts. ``metadata`` is shallow-copied so the returned event
        does not alias the dict nested inside ``raw``. ``raw`` is set to the
        full input dict.
        """
        msg: dict[str, Any] = data.get("message", {})
        content = tuple(
            ContentPart(**part) for part in msg.get("content", []) if isinstance(part, dict)
        )
        return cls(
            event_id=msg.get("event_id", ""),
            sequence=msg.get("sequence", 0),
            timestamp=data.get("timestamp", ""),
            session_id=msg.get("session_id", ""),
            event_type=EventType(data["type"]),
            item_id=msg.get("item_id"),
            item_kind=ItemKind(msg["item_kind"]) if msg.get("item_kind") else None,
            item_status=ItemStatus(msg["item_status"]) if msg.get("item_status") else None,
            content=content,
            delta=msg.get("delta"),
            tool_kind=ToolKind(msg["tool_kind"]) if msg.get("tool_kind") else None,
            cost_usd=msg.get("cost_usd"),
            duration_ms=msg.get("duration_ms"),
            error_message=msg.get("error_message"),
            metadata=dict(msg.get("metadata", {})),
            raw=data,
        )


# ---------------------------------------------------------------------------
# Stream parser — Claude Code NDJSON → UniversalEvent
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ToolInfo:
    name: str
    input_buffer: str = ""


@dataclass(frozen=True)
class ParserState:
    """Immutable snapshot of stream parser state.

    Construct arbitrary states to test specific parsing branches without
    replaying full event sequences.

    Note: ``tool_map`` and ``active_blocks`` are shallow-frozen — the dataclass
    prevents rebinding, but the dicts themselves are mutable Python objects.
    All pure functions in this module treat them as read-only, producing new
    dicts on mutation. External code holding a ParserState reference must not
    mutate the contained dicts.
    """

    session_id: str = ""
    sequence: int = 0
    tool_map: dict[str, _ToolInfo] = field(default_factory=dict)
    active_blocks: dict[int, dict[str, Any]] = field(default_factory=dict)
    turn_active: bool = False
    persistent: bool = False
    turn_count: int = 0
    in_replay: bool = False


def _make_event(
    state: ParserState,
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
) -> tuple[ParserState, UniversalEvent]:
    seq = state.sequence + 1
    new_state = replace(state, sequence=seq)
    event = UniversalEvent(
        event_id=str(uuid.uuid4()),
        sequence=seq,
        timestamp=datetime.now(timezone.utc).isoformat(),
        session_id=state.session_id,
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
    return new_state, event


# ---------------------------------------------------------------------------
# Pure parse functions — state in, (state, events) out
# ---------------------------------------------------------------------------


def _parse_system(
    state: ParserState, data: dict[str, Any]
) -> tuple[ParserState, UniversalEvent | None]:
    subtype = data.get("subtype")

    if subtype == "api_retry":
        new_state, event = _make_event(
            state,
            EventType.API_RETRY,
            metadata={
                "attempt": data.get("attempt"),
                "max_retries": data.get("max_retries"),
                "retry_delay_ms": data.get("retry_delay_ms"),
                "error_status": data.get("error_status"),
                "error": data.get("error"),
            },
            raw=data,
        )
        return new_state, event

    if subtype != "init":
        return state, None

    # Suppress duplicate init emitted after replay cycle completes
    if state.in_replay:
        sid = data.get("session_id", "") or state.session_id
        return replace(state, session_id=sid, in_replay=False), None

    sid = data.get("session_id", "") or state.session_id
    turn_count = state.turn_count + 1
    tools = data.get("tools", [])
    event_type = (
        EventType.TURN_STARTED if state.persistent and turn_count > 1 else EventType.SESSION_STARTED
    )
    intermediate = replace(state, session_id=sid, turn_count=turn_count)
    new_state, event = _make_event(
        intermediate,
        event_type,
        metadata={"tools": tools, "turn": turn_count},
        raw=data,
    )
    return new_state, event


def _on_block_start(
    state: ParserState, event: dict[str, Any], raw: dict[str, Any]
) -> tuple[ParserState, UniversalEvent | None]:
    block = event.get("content_block", {})
    block_type = block.get("type", "")
    index = event.get("index", 0)

    new_blocks = dict(state.active_blocks)
    new_blocks[index] = {"type": block_type, "id": block.get("id")}

    if block_type == "thinking":
        item_id = str(uuid.uuid4())
        new_blocks[index]["item_id"] = item_id
        intermediate = replace(state, active_blocks=new_blocks, turn_active=True)
        new_state, ev = _make_event(
            intermediate,
            EventType.ITEM_STARTED,
            item_id=item_id,
            item_kind=ItemKind.REASONING,
            item_status=ItemStatus.IN_PROGRESS,
            raw=raw,
        )
        return new_state, ev

    if block_type == "text":
        item_id = str(uuid.uuid4())
        new_blocks[index]["item_id"] = item_id
        intermediate = replace(state, active_blocks=new_blocks, turn_active=True)
        new_state, ev = _make_event(
            intermediate,
            EventType.ITEM_STARTED,
            item_id=item_id,
            item_kind=ItemKind.MESSAGE,
            item_status=ItemStatus.IN_PROGRESS,
            raw=raw,
        )
        return new_state, ev

    if block_type == "tool_use":
        tool_name = block.get("name", "")
        call_id = block.get("id", "")
        item_id = call_id or str(uuid.uuid4())
        new_blocks[index]["item_id"] = item_id
        new_tool_map = dict(state.tool_map)
        new_tool_map[call_id] = _ToolInfo(name=tool_name)
        intermediate = replace(
            state, tool_map=new_tool_map, active_blocks=new_blocks, turn_active=True
        )
        new_state, ev = _make_event(
            intermediate,
            EventType.ITEM_STARTED,
            item_id=item_id,
            item_kind=ItemKind.TOOL_CALL,
            item_status=ItemStatus.IN_PROGRESS,
            tool_kind=classify_tool(tool_name),
            content=(ContentPart(type="tool_call", tool_name=tool_name, call_id=call_id),),
            raw=raw,
        )
        return new_state, ev

    return replace(state, active_blocks=new_blocks, turn_active=True), None


def _on_block_delta(
    state: ParserState, event: dict[str, Any], raw: dict[str, Any]
) -> tuple[ParserState, UniversalEvent | None]:
    delta = event.get("delta", {})
    delta_type = delta.get("type", "")
    index = event.get("index", 0)
    block_info = state.active_blocks.get(index, {})
    item_id = block_info.get("item_id")

    if delta_type == "text_delta":
        text = delta.get("text", "")
        new_state, ev = _make_event(
            state,
            EventType.ITEM_DELTA,
            item_id=item_id,
            item_kind=ItemKind.MESSAGE,
            delta=text,
            raw=raw,
        )
        return new_state, ev

    if delta_type == "thinking_delta":
        text = delta.get("thinking", "")
        new_state, ev = _make_event(
            state,
            EventType.ITEM_DELTA,
            item_id=item_id,
            item_kind=ItemKind.REASONING,
            delta=text,
            raw=raw,
        )
        return new_state, ev

    if delta_type == "input_json_delta":
        chunk = delta.get("partial_json", "")
        call_id = block_info.get("id", "")
        new_tool_map = state.tool_map
        if call_id and call_id in state.tool_map:
            old_info = state.tool_map[call_id]
            new_tool_map = dict(state.tool_map)
            new_tool_map[call_id] = _ToolInfo(
                name=old_info.name, input_buffer=old_info.input_buffer + chunk
            )
        tool_name = new_tool_map.get(call_id, _ToolInfo("")).name if call_id else None
        intermediate = replace(state, tool_map=new_tool_map)
        new_state, ev = _make_event(
            intermediate,
            EventType.ITEM_DELTA,
            item_id=item_id,
            item_kind=ItemKind.TOOL_CALL,
            delta=chunk,
            tool_kind=classify_tool(tool_name) if tool_name else None,
            raw=raw,
        )
        return new_state, ev

    return state, None


def _on_block_stop(
    state: ParserState, event: dict[str, Any], raw: dict[str, Any]
) -> tuple[ParserState, UniversalEvent | None]:
    index = event.get("index", 0)
    new_blocks = dict(state.active_blocks)
    block_info = new_blocks.pop(index, {})
    block_type = block_info.get("type", "")
    item_id = block_info.get("item_id")

    intermediate = replace(state, active_blocks=new_blocks)

    if block_type == "tool_use":
        call_id = block_info.get("id", "")
        tool_info = state.tool_map.get(call_id)
        tool_name = tool_info.name if tool_info else None
        tk = classify_tool(tool_name) if tool_name else None

        metadata: dict[str, Any] = {}
        if tk == ToolKind.AGENT and tool_info and tool_info.input_buffer:
            try:
                agent_input = json.loads(tool_info.input_buffer)
                metadata["subagent_type"] = agent_input.get("subagent_type")
                metadata["description"] = agent_input.get("description")
                metadata["prompt"] = agent_input.get("prompt")
            except (json.JSONDecodeError, ValueError):
                pass

        new_state, ev = _make_event(
            intermediate,
            EventType.ITEM_COMPLETED,
            item_id=item_id,
            item_kind=ItemKind.TOOL_CALL,
            item_status=ItemStatus.COMPLETED,
            tool_kind=tk,
            metadata=metadata if metadata else {},
            raw=raw,
        )
        return new_state, ev

    if block_type == "thinking":
        new_state, ev = _make_event(
            intermediate,
            EventType.ITEM_COMPLETED,
            item_id=item_id,
            item_kind=ItemKind.REASONING,
            item_status=ItemStatus.COMPLETED,
            raw=raw,
        )
        return new_state, ev

    if block_type == "text":
        new_state, ev = _make_event(
            intermediate,
            EventType.ITEM_COMPLETED,
            item_id=item_id,
            item_kind=ItemKind.MESSAGE,
            item_status=ItemStatus.COMPLETED,
            raw=raw,
        )
        return new_state, ev

    return intermediate, None


def _parse_stream_event(
    state: ParserState, data: dict[str, Any]
) -> tuple[ParserState, UniversalEvent | None]:
    event = data.get("event", {})
    se_type = event.get("type", "")

    if se_type == "content_block_start":
        return _on_block_start(state, event, data)
    if se_type == "content_block_delta":
        return _on_block_delta(state, event, data)
    if se_type == "content_block_stop":
        return _on_block_stop(state, event, data)
    if se_type == "message_stop":
        return replace(state, active_blocks={}, turn_active=False), None

    return state, None


def _parse_assistant(
    state: ParserState, data: dict[str, Any]
) -> tuple[ParserState, UniversalEvent | None]:
    message = data.get("message", {})

    new_tool_map = dict(state.tool_map)
    for block in message.get("content", []):
        if block.get("type") == "tool_use":
            call_id = block.get("id", "")
            name = block.get("name", "")
            new_tool_map[call_id] = _ToolInfo(
                name=name,
                input_buffer=json.dumps(block.get("input", {})),
            )

    return replace(state, tool_map=new_tool_map), None


def _parse_user(
    state: ParserState, data: dict[str, Any]
) -> tuple[ParserState, list[UniversalEvent]]:
    if data.get("isReplay"):
        return replace(state, in_replay=True), []

    message = data.get("message", {})
    content = message.get("content", [])
    if not isinstance(content, list):
        return state, []

    events: list[UniversalEvent] = []
    current_state = state

    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_result":
            continue
        call_id = block.get("tool_use_id", "")
        tool_info = current_state.tool_map.get(call_id)
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

        current_state, ev = _make_event(
            current_state,
            EventType.ITEM_COMPLETED,
            item_id=call_id,
            item_kind=ItemKind.TOOL_RESULT,
            item_status=ItemStatus.FAILED if is_error else ItemStatus.COMPLETED,
            tool_kind=tk,
            content=tuple(content_parts),
            raw=data,
        )
        events.append(ev)

    return current_state, events


def _parse_result(
    state: ParserState, data: dict[str, Any]
) -> tuple[ParserState, list[UniversalEvent]]:
    import logging

    logger = logging.getLogger("harnessbox.streaming")

    if state.in_replay:
        return state, []

    sid = state.session_id or data.get("session_id", "")
    is_error = data.get("is_error", False)
    if is_error:
        logger.error("Claude agent error - result data: %s", data)

    current_state = replace(state, session_id=sid)

    events: list[UniversalEvent] = []

    for denial in (
        data.get("result", {}).get("permission_denials", [])
        if isinstance(data.get("result"), dict)
        else []
    ):
        current_state, ev = _make_event(
            current_state,
            EventType.PERMISSION_REQUESTED,
            metadata={"tool": denial.get("tool_name", "")},
            raw=data,
        )
        events.append(ev)

    result_text = data.get("result", "")
    if isinstance(result_text, dict):
        result_text = result_text.get("text", str(result_text))

    event_type = EventType.TURN_ENDED if current_state.persistent else EventType.SESSION_ENDED

    metadata: dict[str, Any] = {
        "is_error": is_error,
        "result": str(result_text) if not is_error else None,
        "turn": current_state.turn_count,
    }

    usage = data.get("usage")
    if isinstance(usage, dict):
        metadata["usage"] = {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
        }

    model_usage = data.get("modelUsage")
    if isinstance(model_usage, dict) and model_usage:
        metadata["model_usage"] = model_usage

    num_turns = data.get("num_turns")
    if num_turns is not None:
        metadata["num_turns"] = num_turns

    duration_api_ms = data.get("duration_api_ms")
    if duration_api_ms is not None:
        metadata["duration_api_ms"] = duration_api_ms

    current_state, ev = _make_event(
        current_state,
        event_type,
        cost_usd=data.get("total_cost_usd"),
        duration_ms=data.get("duration_ms"),
        error_message=str(result_text) if is_error else None,
        metadata=metadata,
        raw=data,
    )
    events.append(ev)
    return current_state, events


def _parse_control_request(
    state: ParserState, data: dict[str, Any]
) -> tuple[ParserState, list[UniversalEvent]]:
    request = data.get("request", {})
    tool_name = request.get("tool_name", "")
    tool_input = request.get("input", {})

    if tool_name == "AskUserQuestion":
        new_state, ev = _make_event(
            state,
            EventType.INPUT_REQUESTED,
            metadata={
                "request_id": data.get("request_id"),
                "questions": tool_input.get("questions", [])
                if isinstance(tool_input, dict)
                else [],
            },
            raw=data,
        )
        return new_state, [ev]

    new_state, ev = _make_event(
        state,
        EventType.PERMISSION_REQUESTED,
        metadata={
            "request_id": data.get("request_id"),
            "subtype": request.get("subtype"),
            "tool_name": tool_name,
            "tool_input": tool_input,
        },
        raw=data,
    )
    return new_state, [ev]


def parse_line(state: ParserState, line: str) -> tuple[ParserState, list[UniversalEvent]]:
    """Pure parsing function: state in, (new_state, events) out.

    Tests can construct arbitrary ``ParserState`` values to reproduce
    specific state combinations without replaying full event sequences.
    """
    line = line.strip()
    if not line:
        return state, []
    try:
        data = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return state, []
    if not isinstance(data, dict):
        return state, []

    msg_type = data.get("type")

    if msg_type == "system":
        new_state, ev = _parse_system(state, data)
        return new_state, [ev] if ev else []
    if msg_type == "stream_event":
        new_state, ev = _parse_stream_event(state, data)
        return new_state, [ev] if ev else []
    if msg_type == "assistant":
        new_state, ev = _parse_assistant(state, data)
        return new_state, [ev] if ev else []
    if msg_type == "user":
        return _parse_user(state, data)
    if msg_type == "result":
        return _parse_result(state, data)
    if msg_type == "control_request":
        return _parse_control_request(state, data)
    if msg_type == "_process_error":
        new_state, ev = _make_event(
            state,
            EventType.ERROR,
            error_message=data.get("stderr", "process error"),
            raw=data,
        )
        return new_state, [ev]

    return state, []


# ---------------------------------------------------------------------------
# StreamParser — stateful wrapper around pure parse_line
# ---------------------------------------------------------------------------


class StreamParser:
    """Stateful parser converting Claude Code stream-json NDJSON to UniversalEvents.

    Wraps the pure ``parse_line()`` function, maintaining a ``ParserState``
    across calls. Create one per agent session.
    """

    def __init__(self, session_id: str = "", *, persistent: bool = False) -> None:
        self._state = ParserState(session_id=session_id, persistent=persistent)

    @property
    def state(self) -> ParserState:
        """Return the current parser state snapshot."""
        return self._state

    @property
    def session_id(self) -> str:
        """Return the session ID discovered from the stream."""
        return self._state.session_id

    @property
    def tool_map(self) -> dict[str, _ToolInfo]:
        """Current tool call state. Returns a shallow copy."""
        return dict(self._state.tool_map)

    @tool_map.setter
    def tool_map(self, value: dict[str, _ToolInfo]) -> None:
        self._state = replace(self._state, tool_map=value)

    def parse(self, line: str) -> UniversalEvent | None:
        """Parse a line and return the first event, or None."""
        events = self.parse_line(line)
        return events[0] if events else None

    def parse_line(self, line: str) -> list[UniversalEvent]:
        """Parse a line and return zero or more events."""
        new_state, events = parse_line(self._state, line)
        self._state = new_state
        return events

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
        """Create an event and advance sequence. Used by AgentProcess for timeouts."""
        new_state, event = _make_event(
            self._state,
            event_type,
            item_id=item_id,
            item_kind=item_kind,
            item_status=item_status,
            content=content,
            delta=delta,
            tool_kind=tool_kind,
            cost_usd=cost_usd,
            duration_ms=duration_ms,
            error_message=error_message,
            metadata=metadata,
            raw=raw,
        )
        self._state = new_state
        return event


def parse_stream_line(line: str) -> UniversalEvent | None:
    """Stateless convenience for parsing a single stream-json line.

    Returns the first event if the line produces multiple events,
    or None if the line is unparseable.
    """
    _, events = parse_line(ParserState(), line)
    return events[0] if events else None
