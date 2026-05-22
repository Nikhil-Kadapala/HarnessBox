# Security Policies

Security policies control what the AI agent can do inside the sandbox. They restrict tool usage, shell commands, file access, and network activity — enforced at the agent configuration level and via runtime hook scripts.

```python
from harnessbox import WorkspaceConfig
from harnessbox.security.policy import SecurityPolicy

policy = SecurityPolicy(
    denied_tools=["computer", "mcp__dangerous_server"],
    bash_deny_patterns=["rm -rf /", "curl * | bash"],
    read_deny_patterns=["**/.env", "**/credentials.json"],
)

hb = HarnessBox(
    provider="e2b",
    harness="claude-code",
    security_policy=policy,
    workspace_config=WorkspaceConfig(),
)
```

## How Enforcement Works

Security policies are enforced at two layers:

1. **Agent settings** — `denied_tools` and path restrictions are written into the agent's `settings.json`, which the agent respects natively.
2. **PreToolUse hooks** — Shell scripts that intercept tool calls before execution. If a hook exits non-zero, the tool call is blocked.

This dual-layer approach means restrictions work even if the agent tries to circumvent them through indirect means.

## Denied Tools

Block specific agent tools by name:

```python
policy = SecurityPolicy(
    denied_tools=[
        "computer",           # Block computer-use tool
        "mcp__slack__send",   # Block MCP Slack integration
    ],
)
```

## Bash Deny Patterns

Block shell commands matching glob patterns:

```python
policy = SecurityPolicy(
    bash_deny_patterns=[
        "rm -rf /*",          # Prevent destructive deletions
        "curl * | bash",      # Prevent pipe-to-shell
        "wget *",            # Block downloads
        "ssh *",             # Block SSH
    ],
)
```

## Read Deny Patterns

Prevent the agent from reading sensitive files:

```python
policy = SecurityPolicy(
    read_deny_patterns=[
        "**/.env",
        "**/.env.*",
        "**/credentials.json",
        "**/secrets.yaml",
        "**/.ssh/*",
    ],
)
```

## Credential Guards

Credential guards are pre-built security rule sets that protect specific credential types. Each guard defines bash deny globs, read deny globs, and hook regexes together as a single unit.

```python
from harnessbox.security.guards import GUARD_CATALOG, merge_guard_sets

# See available guards
from harnessbox.security.guards import ALL_GUARD_NAMES
print(ALL_GUARD_NAMES)
# ['aws', 'gcp', 'azure', 'github', 'anthropic', 'openai', ...]

# Use specific guards
guards = [GUARD_CATALOG["aws"], GUARD_CATALOG["github"]]
merged = merge_guard_sets(guards)
```

Guards are the single source of truth — they generate both the `settings.json` deny rules and the hook scripts automatically.

## Hook Scripts

PreToolUse hooks are shell scripts generated from credential guard regex patterns. They run before every tool call and can block execution:

```python
from harnessbox.security.hooks import generate_hook_scripts

scripts = generate_hook_scripts(guards)
# Returns shell scripts that intercept tool calls matching guard patterns
```

Hooks follow a fail-open design — if the hook script itself errors, the tool call proceeds. This prioritizes availability over strict blocking.

## Full Example

```python
from harnessbox import HarnessBox, HarnessBoxSecrets, WorkspaceConfig
from harnessbox.security.policy import SecurityPolicy
from harnessbox.security.guards import GUARD_CATALOG, merge_guard_sets

# Combine guards for comprehensive protection
guards = [
    GUARD_CATALOG["aws"],
    GUARD_CATALOG["gcp"],
    GUARD_CATALOG["github"],
]
merged = merge_guard_sets(guards)

policy = SecurityPolicy(
    denied_tools=["computer"],
    bash_deny_patterns=[
        "rm -rf /*",
        *merged.bash_deny_globs,
    ],
    read_deny_patterns=[
        "**/.env",
        *merged.read_deny_globs,
    ],
)

hb = HarnessBox(
    provider="e2b",
    harness="claude-code",
    workspace_config=WorkspaceConfig(),
    security_policy=policy,
    secrets=HarnessBoxSecrets(
        provider_api_key="your-e2b-key",
        harness_secrets={"ANTHROPIC_API_KEY": "sk-ant-..."},
    ),
)
```

## Related

- [Sandboxes Overview](overview.md) — Full sandbox lifecycle
- [Credential Guards reference](../reference/guards.md) — Complete guard catalog
