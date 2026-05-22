# Streaming Events

When you send a prompt to the agent, responses stream back as typed `UniversalEvent` objects. The SDK parses the agent's NDJSON output (Claude Code's `--output-format stream-json`) into structured events you can handle programmatically.

```python
from harnessbox.streaming import EventType as StreamEventType, ItemKind

async for event in session.send_message("Fix the failing test"):
    match event.event_type:
        case StreamEventType.ITEM_DELTA:
            if event.item_kind == ItemKind.MESSAGE:
                print(event.delta or "", end="")
            elif event.item_kind == ItemKind.REASONING:
                print(event.delta or "", end="")
        case StreamEventType.ITEM_STARTED:
            if event.item_kind == ItemKind.TOOL_CALL:
                print(f"\n[Calling tool: {event.tool_kind}]")
        case StreamEventType.TURN_ENDED:
            print("\n--- Agent finished ---")
```

## Event Types

| Type (Enum) | Description | Key Fields |
|-------------|-------------|------------|
| `SESSION_STARTED` | Session initialized | `session_id` |
| `SESSION_ENDED` | Session terminated | `session_id` |
| `TURN_STARTED` | Agent turn started | `session_id` |
| `TURN_ENDED` | Agent turn completed | `cost_usd`, `duration_ms` |
| `ITEM_STARTED` | Sub-item (message/tool/reasoning) started | `item_id`, `item_kind` |
| `ITEM_DELTA` | Incremental chunk of item content | `item_id`, `item_kind`, `delta` |
| `ITEM_COMPLETED` | Sub-item completed | `item_id`, `item_kind` |
| `ERROR` | An error occurred | `error_message` |

## UniversalEvent

Every event is a `UniversalEvent` dataclass:

```python
from harnessbox.streaming import UniversalEvent, EventType, ItemKind, ItemStatus

event = UniversalEvent(
    event_id="...",
    sequence=1,
    timestamp="...",
    session_id="...",
    event_type=EventType.ITEM_DELTA,
    item_id="...",
    item_kind=ItemKind.MESSAGE,
    item_status=ItemStatus.IN_PROGRESS,
    content=(...),
    delta="Here's the fix...",
    tool_kind=None,
    cost_usd=None,
    duration_ms=None,
    error_message=None,
    metadata={},
)
```

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `event_id` | str | Unique event identifier |
| `sequence` | int | Monotonically increasing sequence number |
| `timestamp` | str | ISO-8601 UTC timestamp |
| `session_id` | str | Session identifier |
| `event_type` | EventType | The event type classification (e.g., `item.delta`) |
| `item_id` | str or None | Identifier for the message/tool/reasoning block |
| `item_kind` | ItemKind or None | Kind of item: `message`, `tool_call`, `tool_result`, `reasoning`, `status` |
| `item_status` | ItemStatus or None | Status of the item: `in_progress`, `completed`, `failed` |
| `content` | tuple[ContentPart, ...] | Structured content representation |
| `delta` | str or None | Incremental text content (for MESSAGE, REASONING, status, etc.) |
| `tool_kind` | ToolKind or None | Category of tool: `bash`, `file_change`, `file_read`, `web`, `agent`, `other` |
| `cost_usd` | float or None | USD cost accrued for this turn (available on `TURN_ENDED`) |
| `duration_ms` | int or None | Execution duration in milliseconds (available on `TURN_ENDED`) |
| `error_message` | str or None | Error description |
| `metadata` | dict | Additional raw metadata |

## StreamParser

The `StreamParser` is a stateful NDJSON parser that maps raw agent output to `UniversalEvent` objects:

```python
from harnessbox.streaming import StreamParser

parser = StreamParser()

for line in ndjson_lines:
    events = parser.parse_line(line)
    for event in events:
        handle(event)
```

The parser maintains internal state to correctly associate tool results with their calls, track the session ID, and deduplicate turn-ended signals.

## Tool Classification

Tools are classified by kind for UI rendering:

```python
from harnessbox.streaming import classify_tool, ToolKind

kind = classify_tool("Bash")        # ToolKind.BASH
kind = classify_tool("Read")        # ToolKind.FILE_READ
kind = classify_tool("Write")       # ToolKind.FILE_CHANGE
kind = classify_tool("WebSearch")   # ToolKind.WEB
```

| ToolKind | Tools |
|----------|-------|
| `BASH` | Bash, Shell |
| `FILE_READ` | Read, Grep, Glob |
| `FILE_CHANGE` | Write, Edit, MultiEdit |
| `WEB` | WebFetch, WebSearch |
| `AGENT` | Agent |
| `OTHER` | Everything else |

## Cost Tracking

`TURN_ENDED` events include cost metadata when available:

```python
async for event in session.send_message("Refactor auth"):
    if event.event_type == StreamEventType.TURN_ENDED:
        print(f"Cost: ${event.cost_usd:.4f}, Duration: {event.duration_ms}ms")
```

## Related

- [Sandboxes Overview](overview.md) — Full sandbox API
- [Running Commands](commands.md) — Direct command execution (non-streaming)
