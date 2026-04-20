"""HarnessBox — Sandbox security primitives and unified API for AI coding agents."""

from harnessbox._version import __version__
from harnessbox.harness import (
    HarnessTypeConfig,
    get_harness_type,
    list_harness_types,
    register_harness_type,
)
from harnessbox.hooks import BLOCKED_PATTERNS, GUARD_BASH_SCRIPT, matches_blocked_pattern
from harnessbox.lifecycle import (
    VALID_TRANSITIONS,
    InvalidTransitionError,
    SessionState,
    validate_transition,
)
from harnessbox.providers import CommandHandle, CommandResult, SandboxProvider
from harnessbox.sandbox import Sandbox
from harnessbox.security import SecurityPolicy, build_settings, credential_deny_rules
from harnessbox.workspace import GitWorkspace, MountWorkspace, Workspace

__all__ = [
    "__version__",
    # Phase 1 — Security primitives
    "BLOCKED_PATTERNS",
    "GUARD_BASH_SCRIPT",
    "InvalidTransitionError",
    "SecurityPolicy",
    "SessionState",
    "VALID_TRANSITIONS",
    "build_settings",
    "credential_deny_rules",
    "matches_blocked_pattern",
    "validate_transition",
    # Phase 2 — Sandbox abstraction
    "CommandHandle",
    "CommandResult",
    "HarnessTypeConfig",
    "Sandbox",
    "SandboxProvider",
    "get_harness_type",
    "list_harness_types",
    "register_harness_type",
    # Phase 3 — Workspace primitives
    "GitWorkspace",
    "MountWorkspace",
    "Workspace",
]
