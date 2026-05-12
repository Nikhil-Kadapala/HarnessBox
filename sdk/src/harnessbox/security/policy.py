"""Security policy engine — generates Claude Code settings.json deny rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SecurityPolicy:
    """Declarative security policy for a sandboxed Claude Code session.

    Attributes:
        denied_tools: Tool names to block (e.g. ``["WebFetch", "Agent"]``).
        denied_bash_patterns: Additional bash deny-rule glob patterns.
        deny_network: If True, also blocks ``WebFetch`` and ``WebSearch``.
        credential_guards: Which credential guard sets to activate.
            ``True`` or ``"all"`` enables all guards (default).
            ``False`` disables guards.
            A list of names (e.g. ``["aws", "gcp"]``) enables specific sets.
        extra_bash_guards: Additional Bash deny globs merged into guard output.
        extra_read_guards: Additional Read deny globs merged into guard output.
    """

    denied_tools: list[str] = field(default_factory=list)
    denied_bash_patterns: list[str] = field(default_factory=list)
    deny_network: bool = False
    credential_guards: bool | str | list[str] = True
    extra_bash_guards: list[str] = field(default_factory=list)
    extra_read_guards: list[str] = field(default_factory=list)


def resolve_credential_guards(policy: SecurityPolicy) -> frozenset[str] | None:
    """Resolve the effective set of credential guard names from a policy.

    Returns None if guards are disabled, or a frozenset of guard set names.
    """
    from harnessbox.security.guards import ALL_GUARD_NAMES

    guards = policy.credential_guards

    if guards is False:
        return None

    if guards is True or guards == "all":
        return ALL_GUARD_NAMES

    if isinstance(guards, str):
        if guards not in ALL_GUARD_NAMES:
            raise ValueError(
                f"Unknown credential guard set {guards!r}. "
                f"Valid sets: {', '.join(sorted(ALL_GUARD_NAMES))}"
            )
        return frozenset({guards})

    if isinstance(guards, list):
        unknown = set(guards) - ALL_GUARD_NAMES
        if unknown:
            raise ValueError(
                f"Unknown credential guard set(s): {', '.join(sorted(unknown))}. "
                f"Valid sets: {', '.join(sorted(ALL_GUARD_NAMES))}"
            )
        return frozenset(guards)

    raise TypeError(f"credential_guards must be bool, str, or list[str]; got {type(guards)}")


def build_settings(policy: SecurityPolicy) -> dict[str, Any]:
    """Generate a ``.claude/settings.json`` dict from a SecurityPolicy.

    The returned dict is JSON-serializable and ready to write into a sandbox.
    """
    deny: dict[str, list[str]] = {"Bash": [], "Read": []}

    guard_names = resolve_credential_guards(policy)
    if guard_names is not None:
        from harnessbox.security.guards import merge_guard_sets

        merged = merge_guard_sets(
            guard_names,
            extra_bash_guards=tuple(policy.extra_bash_guards),
            extra_read_guards=tuple(policy.extra_read_guards),
        )
        deny["Bash"] = list(merged.bash_deny_globs)
        deny["Read"] = list(merged.read_deny_globs)

    for pattern in policy.denied_bash_patterns:
        if pattern not in deny["Bash"]:
            deny["Bash"].append(pattern)

    tool_deny: list[str] = list(policy.denied_tools)

    if policy.deny_network:
        for tool in ("WebFetch", "WebSearch"):
            if tool not in tool_deny:
                tool_deny.append(tool)

    for tool in tool_deny:
        deny[tool] = ["*"]

    settings: dict[str, Any] = {
        "permissions": {
            "allow": [],
            "deny": deny,
        },
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python3 /workspace/.claude/hooks/guard_bash.py",
                        }
                    ],
                }
            ],
        },
    }

    return settings
