"""HarnessBox — Sandbox security primitives and unified API for AI coding agents."""

from harnessbox._version import __version__
from harnessbox.config.harness import (
    HarnessTypeConfig,
    get_harness_type,
    list_harness_types,
    register_harness_type,
)
from harnessbox.events import EventBuffer
from harnessbox.lifecycle import (
    VALID_TRANSITIONS,
    InvalidTransitionError,
    SessionState,
    validate_transition,
)
from harnessbox.process import AgentProcess
from harnessbox.providers import CommandHandle, CommandResult, SandboxProvider
from harnessbox.sandbox import InteractiveSession, Sandbox
from harnessbox.security.events import (
    CallbackHandler,
    EventHandler,
    EventType,
    JsonLogger,
    SandboxEvent,
)
from harnessbox.security.guards import (
    ALL_GUARD_NAMES,
    GUARD_CATALOG,
    CredentialGuardSet,
    merge_guard_sets,
)
from harnessbox.security.policy import SecurityPolicy, build_settings
from harnessbox.streaming import (
    AgentStreamEvent,
    ContentPart,
    ItemKind,
    ItemStatus,
    StreamParser,
    ToolKind,
    UniversalEvent,
    classify_tool,
    parse_stream_line,
)
from harnessbox.streaming import (
    EventType as StreamEventType,
)
from harnessbox.workspace import GitStatus, GitWorkspace, Workspace

__all__ = [
    "__version__",
    # Security
    "ALL_GUARD_NAMES",
    "CredentialGuardSet",
    "GUARD_CATALOG",
    "InvalidTransitionError",
    "SecurityPolicy",
    "SessionState",
    "VALID_TRANSITIONS",
    "build_settings",
    "merge_guard_sets",
    "validate_transition",
    # Streaming
    "AgentStreamEvent",
    "ContentPart",
    "InteractiveSession",
    "ItemKind",
    "ItemStatus",
    "StreamEventType",
    "StreamParser",
    "ToolKind",
    "UniversalEvent",
    "classify_tool",
    "parse_stream_line",
    # Process
    "AgentProcess",
    # Sandbox
    "CommandHandle",
    "CommandResult",
    "HarnessTypeConfig",
    "Sandbox",
    "SandboxProvider",
    "get_harness_type",
    "list_harness_types",
    "register_harness_type",
    # Workspace
    "GitStatus",
    "GitWorkspace",
    "Workspace",
    # Event buffer
    "EventBuffer",
    # Events
    "CallbackHandler",
    "EventHandler",
    "EventType",
    "JsonLogger",
    "SandboxEvent",
]
