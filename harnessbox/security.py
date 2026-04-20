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
        include_credential_guards: If True, merges baseline credential deny rules.
    """

    denied_tools: list[str] = field(default_factory=list)
    denied_bash_patterns: list[str] = field(default_factory=list)
    deny_network: bool = False
    include_credential_guards: bool = True


def credential_deny_rules() -> dict[str, list[str]]:
    """Baseline deny rules protecting credentials in any sandbox.

    Returns a dict with ``"Bash"`` and ``"Read"`` keys, each mapping to a
    list of glob patterns that should be denied.
    """
    return {
        "Bash": [
            "env",
            "env *",
            "printenv",
            "printenv *",
            "export -p",
            "export -p *",
            "set",
            "compgen -e",
            "compgen -e *",
            "cat /proc/*/environ",
            "cat /proc/self/environ",
            "strings /proc/*/environ",
            "xargs -0 < /proc/*/environ",
            "curl http://169.254.169.254/*",
            "curl http://metadata.google.internal/*",
            "wget http://169.254.169.254/*",
            "wget http://metadata.google.internal/*",
            "cat ~/.aws/credentials",
            "cat ~/.aws/config",
            "git config credential.helper",
            "git config credential.*",
            "cat ~/.git-credentials",
        ],
        "Read": [
            ".env",
            ".env.*",
            "**/.env",
            "**/.env.*",
            ".claude/settings.json",
            ".claude/settings.local.json",
            "~/.aws/credentials",
            "~/.aws/config",
            ".git/config",
            ".git-credentials",
            "~/.git-credentials",
        ],
    }


def build_settings(policy: SecurityPolicy) -> dict[str, Any]:
    """Generate a ``.claude/settings.json`` dict from a SecurityPolicy.

    The returned dict is JSON-serializable and ready to write into a sandbox.
    """
    deny: dict[str, list[str]] = {}

    if policy.include_credential_guards:
        baseline = credential_deny_rules()
        deny["Bash"] = list(baseline["Bash"])
        deny["Read"] = list(baseline["Read"])
    else:
        deny["Bash"] = []
        deny["Read"] = []

    for pattern in policy.denied_bash_patterns:
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
