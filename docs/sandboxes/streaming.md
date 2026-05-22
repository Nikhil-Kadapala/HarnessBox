# Streaming Events

When you send a prompt to the agent, responses stream back as typed `UniversalEvent` objects. The SDK parses the agent's NDJSON output (Claude Code's `--output-format stream-json`) into structured events you can handle programmatically.

```python
async for event in session.send_message("Fix the failing test"):
    match event.event_type:
        case StreamEventType.AGENT_TEXT:
            print(event.text, end="")
        case StreamEventType.TOOL_CALL:
            print(f"\n[Calling {event.tool_name}]")
        case StreamEventType.TOOL_RESULT:
            print(f"[Result: {event.text[:100]}]")
        case StreamEventType.TURN_ENDED:
            print("\n--- Agent finished ---")
```

## Event Types

| Type | Description | Key Fields |
|------|-------------|------------|
| `USER_PROMPT` | Prompt sent to the agent | `text` |
| `AGENT_TEXT` | Text output from the agent | `text` |
| `THINKING` | Agent's internal reasoning (extended thinking) | `text` |
| `TOOL_CALL` | Agent invoking a tool | `tool_name`, `tool_input`, `tool_call_id` |
| `TOOL_RESULT` | Result returned from a tool | `text`, `tool_call_id` |
| `TURN_ENDED` | Agent finished responding | `metadata` (cost, duration) |
| `SESSION_STARTED` | Agent session initialized | |
| `SESSION_ENDED` | Session terminated | |
| `ERROR` | Error occurred | `error_message` |

## UniversalEvent

Every event is a `UniversalEvent` dataclass:

```python
from harnessbox.streaming import UniversalEvent, StreamParser

event = UniversalEvent(
    event_type=StreamEventType.AGENT_TEXT,
    text="Here's the fix...",
    tool_name=None,
    tool_input=None,
    tool_call_id=None,
    error_message=None,
    metadata=None,
)
```

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `event_type` | EventType | The event classification |
| `text` | str or None | Text content (for text, thinking, tool results) |
| `tool_name` | str or None | Tool being called (Bash, Read, Write, Edit, etc.) |
| `tool_input` | str or None | JSON input to the tool |
| `tool_call_id` | str or None | Unique ID linking tool calls to results |
| `error_message` | str or None | Error description |
| `metadata` | dict or None | Additional data (cost metrics on TURN_ENDED) |

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

kind = classify_tool("Bash")        # ToolKind.COMMAND
kind = classify_tool("Read")        # ToolKind.FILE_READ
kind = classify_tool("Write")       # ToolKind.FILE_WRITE
kind = classify_tool("WebSearch")   # ToolKind.NETWORK
```

| ToolKind | Tools |
|----------|-------|
| `COMMAND` | Bash |
| `FILE_READ` | Read, Grep, Glob |
| `FILE_WRITE` | Write, Edit |
| `NETWORK` | WebFetch, WebSearch |
| `MCP` | Any `mcp__*` tool |
| `OTHER` | Everything else |

## Cost Tracking

`TURN_ENDED` events include cost metadata when available:

```python
async for event in session.send_message("Refactor auth"):
    if event.event_type == StreamEventType.TURN_ENDED and event.metadata:
        cost = event.metadata.get("cost_usd")
        duration = event.metadata.get("duration_ms")
        print(f"Cost: ${cost:.4f}, Duration: {duration}ms")
```

## Related

- [Sandboxes Overview](overview.md) — Full sandbox API
- [Running Commands](commands.md) — Direct command execution (non-streaming)
