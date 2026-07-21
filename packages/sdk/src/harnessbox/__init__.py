"""HarnessBox — Sandbox security primitives and unified API for AI coding agents."""

from typing import TYPE_CHECKING, Any

from harnessbox._version import __version__
from harnessbox.config.harness import (
    HarnessTypeConfig,
    get_harness_type,
    list_harness_types,
    register_harness_type,
)
from harnessbox.config.pipeline import (
    InitializeContext,
    InitializeSandbox,
    InitializeStep,
    initialize_sandbox,
)
from harnessbox.cost import CostMetrics, ModelCost, parse_cost_data
from harnessbox.credentials import (
    CredentialProbe,
    CredentialStatus,
    build_claude_env_vars,
    build_gcloud_env_vars,
    detect_claude_auth_mode,
    detect_credentials,
)
from harnessbox.events import EventBuffer
from harnessbox.harnessbox import (
    HarnessBox,
    HarnessBoxSecrets,
    Session,
    Snapshot,
    WorkspaceConfig,
)
from harnessbox.lifecycle import (
    VALID_RUNTIME_TRANSITIONS,
    InvalidTransitionError,
    RuntimeState,
    validate_runtime_transition,
)
from harnessbox.process import AgentProcess
from harnessbox.providers import CommandResult, SandboxDeadError, SandboxProvider
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
    Attachment,
    ContentPart,
    ItemKind,
    ItemStatus,
    ParserState,
    StreamParser,
    ToolKind,
    UniversalEvent,
    classify_tool,
    parse_line,
    parse_stream_line,
)
from harnessbox.streaming import EventType as StreamEventType
from harnessbox.types import AgentResponse
from harnessbox.workspace import GitBranchAlreadyExistsError, GitRepoConfig, GitStatus, Workspace

if TYPE_CHECKING:
    from harnessbox.client import (
        HarnessBoxClient,
        PromptStreamError,
        WorkspaceCreationError,
        WorkspaceInfo,
    )

# The HTTP client lives behind the optional ``client`` extra (httpx). Import it
# lazily so ``import harnessbox`` keeps zero runtime dependencies — accessing
# HarnessBoxClient et al. without the extra raises a clear ImportError.
_CLIENT_EXPORTS = frozenset(
    {"HarnessBoxClient", "PromptStreamError", "WorkspaceCreationError", "WorkspaceInfo"}
)


def __getattr__(name: str) -> Any:
    if name in _CLIENT_EXPORTS:
        from harnessbox import client

        return getattr(client, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "__version__",
    # Server client
    "HarnessBoxClient",
    "PromptStreamError",
    "WorkspaceCreationError",
    "WorkspaceInfo",
    # Cost tracking
    "CostMetrics",
    "ModelCost",
    "parse_cost_data",
    # Security
    "ALL_GUARD_NAMES",
    "CredentialGuardSet",
    "GUARD_CATALOG",
    "InvalidTransitionError",
    "SecurityPolicy",
    "RuntimeState",
    "VALID_RUNTIME_TRANSITIONS",
    "build_settings",
    "merge_guard_sets",
    "validate_runtime_transition",
    # Streaming
    "Attachment",
    "ContentPart",
    "InteractiveSession",
    "ItemKind",
    "ItemStatus",
    "ParserState",
    "StreamEventType",
    "StreamParser",
    "ToolKind",
    "UniversalEvent",
    "classify_tool",
    "parse_line",
    "parse_stream_line",
    # Process
    "AgentProcess",
    # Credentials
    "CredentialProbe",
    "CredentialStatus",
    "build_claude_env_vars",
    "build_gcloud_env_vars",
    "detect_claude_auth_mode",
    "detect_credentials",
    # HarnessBox (public API)
    "HarnessBox",
    "HarnessBoxSecrets",
    "Session",
    "Snapshot",
    "WorkspaceConfig",
    # Sandbox (internal orchestration)
    "AgentResponse",
    "CommandResult",
    "HarnessTypeConfig",
    "Sandbox",
    "SandboxDeadError",
    "SandboxProvider",
    "InitializeContext",
    "InitializeSandbox",
    "InitializeStep",
    "initialize_sandbox",
    "get_harness_type",
    "list_harness_types",
    "register_harness_type",
    # Workspace
    "GitBranchAlreadyExistsError",
    "GitRepoConfig",
    "GitStatus",
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
