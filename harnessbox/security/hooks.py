"""PreToolUse hook guard for intercepting dangerous bash commands in sandboxes."""

from __future__ import annotations

import re
import textwrap

BLOCKED_PATTERNS: list[re.Pattern[str]] = [
    # Environment variable enumeration
    re.compile(r"\benv\b"),
    re.compile(r"\bprintenv\b"),
    re.compile(r"\bexport\s+-p\b"),
    re.compile(r"\bset\b(?=\s*$|\s*\|)"),
    re.compile(r"\bcompgen\s+-e\b"),
    # Python-level credential access
    re.compile(r"os\.environ"),
    re.compile(r"os\.getenv"),
    # AWS credential patterns
    re.compile(r"\$AWS_SECRET_ACCESS_KEY"),
    re.compile(r"\$AWS_ACCESS_KEY_ID"),
    re.compile(r"\$AWS_SESSION_TOKEN"),
    re.compile(r"\$AWS_CONTAINER_CREDENTIALS"),
    re.compile(r"\$\{?AWS_SECRET"),
    re.compile(r"\$\{?AWS_ACCESS"),
    # Exa / generic API key patterns
    re.compile(r"\$EXA_API_KEY"),
    re.compile(r"\$\{?EXA_API_KEY"),
    re.compile(r"\$ANTHROPIC_API_KEY"),
    re.compile(r"\$\{?ANTHROPIC_API_KEY"),
    # /proc filesystem credential exposure
    re.compile(r"/proc/\S*/environ"),
    re.compile(r"/proc/self/environ"),
    # AWS credential files
    re.compile(r"\.aws/credentials"),
    re.compile(r"\.aws/config"),
    # Settings files that may contain secrets
    re.compile(r"\.claude/settings\.local\.json"),
    # IMDS (EC2 metadata service) — credential theft vector
    re.compile(r"169\.254\.169\.254"),
    re.compile(r"metadata\.google\.internal"),
    # Git credential helper — protects workspace auth tokens
    re.compile(r"git\s+config\s+credential\.helper"),
    re.compile(r"\.git-credentials"),
]


def matches_blocked_pattern(command: str) -> bool:
    """Return True if the command matches any blocked pattern."""
    return any(pattern.search(command) for pattern in BLOCKED_PATTERNS)


GUARD_BASH_SCRIPT: str = textwrap.dedent("""\
    #!/usr/bin/env python3
    \"\"\"PreToolUse hook guard — blocks bash commands that access credentials.

    Exit codes:
      0 = allow (also used on errors — fail-open)
      2 = block
    \"\"\"
    import json
    import re
    import sys

    BLOCKED = [
        r"\\benv\\b",
        r"\\bprintenv\\b",
        r"\\bexport\\s+-p\\b",
        r"\\bset\\b(?=\\s*$|\\s*\\|)",
        r"\\bcompgen\\s+-e\\b",
        r"os\\.environ",
        r"os\\.getenv",
        r"\\$AWS_SECRET_ACCESS_KEY",
        r"\\$AWS_ACCESS_KEY_ID",
        r"\\$AWS_SESSION_TOKEN",
        r"\\$AWS_CONTAINER_CREDENTIALS",
        r"\\$\\{?AWS_SECRET",
        r"\\$\\{?AWS_ACCESS",
        r"\\$EXA_API_KEY",
        r"\\$\\{?EXA_API_KEY",
        r"\\$ANTHROPIC_API_KEY",
        r"\\$\\{?ANTHROPIC_API_KEY",
        r"/proc/\\S*/environ",
        r"/proc/self/environ",
        r"\\.aws/credentials",
        r"\\.aws/config",
        r"\\.claude/settings\\.local\\.json",
        r"169\\.254\\.169\\.254",
        r"metadata\\.google\\.internal",
    ]

    _COMPILED = [re.compile(p) for p in BLOCKED]


    def main() -> None:
        try:
            event = json.loads(sys.stdin.read())
        except Exception:
            sys.exit(0)

        tool_name = event.get("tool_name", "")
        if tool_name != "Bash":
            sys.exit(0)

        tool_input = event.get("tool_input", {})
        command = tool_input.get("command", "")

        for pattern in _COMPILED:
            if pattern.search(command):
                print(json.dumps({
                    "decision": "block",
                    "reason": f"Blocked: command matches credential-access pattern {pattern.pattern!r}",
                }))
                sys.exit(2)

        sys.exit(0)


    if __name__ == "__main__":
        main()
""")
