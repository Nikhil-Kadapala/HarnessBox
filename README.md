# HarnessBox

[![PyPI](https://img.shields.io/pypi/v/harnessbox)](https://pypi.org/project/harnessbox/)
[![CI](https://github.com/Nikhil-Kadapala/HarnessBox/actions/workflows/ci.yml/badge.svg)](https://github.com/Nikhil-Kadapala/HarnessBox/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)

Sandbox security, workspace, and harness primitives for AI coding agents.

HarnessBox gives you a single `Sandbox` class that works across cloud providers (E2B, Docker, Daytona, EC2), configures any agent harness (Claude Code, Codex, Gemini CLI, OpenCode), enforces security policies, and optionally clones a git repo into the workspace with one parameter.

```python
from harnessbox import Sandbox, SecurityPolicy, GitWorkspace

sandbox = Sandbox(
    client="e2b",
    api_key="your-e2b-key",
    security_policy=SecurityPolicy(deny_network=True),
    harness="claude-code",
    workspace=GitWorkspace(
        remote="https://github.com/user/repo.git",
        commit_on_exit=True,
    ),
    files={"/workspace/CLAUDE.md": "You are a helpful coding assistant."},
)

await sandbox.setup()

async for line in sandbox.run_prompt("Fix the failing tests"):
    print(line)

await sandbox.end()  # commits + pushes changes back
```

Zero runtime dependencies. Stdlib only. Provider SDKs are optional extras.

## Install

```bash
# From source (until PyPI name is finalized)
pip install -e packages/harnessbox

# With E2B provider
pip install -e "packages/harnessbox[e2b]"
```

## What It Does

```
┌─────────────────────────────────────────────────────┐
│                    YOUR APPLICATION                   │
│                                                       │
│   from harnessbox import Sandbox, SecurityPolicy,    │
│                          GitWorkspace                 │
└──────────────────────┬────────────────────────────────┘
                       │
          ┌────────────▼────────────┐
          │       HarnessBox        │
          │                         │
          │  SecurityPolicy         │  ← deny rules, credential guards,
          │  HarnessTypeConfig      │    PreToolUse hooks
          │  GitWorkspace           │  ← clone repo, commit on exit,
          │  Sandbox                │    snapshots, diff, events
          └────────────┬────────────┘
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
   ┌─────────┐  ┌───────────┐  ┌──────────┐
   │   E2B   │  │  Docker   │  │ Daytona  │  ... any SandboxProvider
   └─────────┘  └───────────┘  └──────────┘
```

## Examples

### Basic Sandbox (No Workspace)

```python
from harnessbox import Sandbox, SecurityPolicy

sandbox = Sandbox(
    client="e2b",
    api_key="...",
    harness="claude-code",
    security_policy=SecurityPolicy(
        denied_tools=["WebFetch", "WebSearch", "Agent"],
        deny_network=True,
    ),
    files={"/workspace/CLAUDE.md": "Analyze the code in /workspace."},
)

await sandbox.setup()
async for line in sandbox.run_prompt("What does this codebase do?"):
    print(line)
await sandbox.kill()
```

### Sandbox with Git Workspace

```python
from harnessbox import Sandbox, GitWorkspace

sandbox = Sandbox(
    client="e2b",
    api_key="...",
    harness="claude-code",
    workspace=GitWorkspace(
        remote="https://github.com/user/my-project.git",
        branch="main",
        commit_on_exit=True,
        auth_token="ghp_...",  # for private repos
    ),
)

await sandbox.setup()
# Repo cloned into /workspace. Agent has full git access.

async for line in sandbox.run_prompt("Add error handling to the API routes"):
    print(line)

await sandbox.end()
# Changes committed and pushed to origin/main
```

### Workspace Snapshots and Diff

```python
sandbox = Sandbox(
    client="e2b",
    api_key="...",
    workspace=GitWorkspace(remote="https://github.com/user/repo.git"),
)
await sandbox.setup()

# Checkpoint before a risky change
await sandbox.workspace.snapshot(sandbox.provider, "/workspace", "before-refactor")

async for line in sandbox.run_prompt("Refactor the auth module"):
    print(line)

# See what changed
diff = await sandbox.workspace.diff(sandbox.provider, "/workspace")
print(diff)

# Undo if it went wrong
await sandbox.workspace.restore(sandbox.provider, "/workspace", "before-refactor")

await sandbox.kill()
```

### Push Failure Recovery

```python
sandbox = Sandbox(
    client="e2b",
    api_key="...",
    workspace=GitWorkspace(
        remote="https://github.com/user/repo.git",
        commit_on_exit=True,
    ),
)
await sandbox.setup()
async for _ in sandbox.run_prompt("Make some changes"):
    pass
await sandbox.end()

# If push failed, the committed files are still accessible
if sandbox.unpushed_files:
    print("Push failed. Recovered files:")
    for path, content in sandbox.unpushed_files.items():
        print(f"  {path}: {len(content)} bytes")
```

### Workspace Events

```python
def on_push_failure(error, branch):
    send_slack_alert(f"Push to {branch} failed: {error}")

sandbox = Sandbox(
    client="e2b",
    api_key="...",
    workspace=GitWorkspace(
        remote="https://github.com/user/repo.git",
        commit_on_exit=True,
        on_clone_start=lambda **kw: print(f"Cloning {kw['remote']}..."),
        on_clone_complete=lambda **kw: print(f"Clone {'OK' if kw['success'] else 'FAILED'}"),
        on_push_failure=on_push_failure,
    ),
)
```

### Setup Script

Run a shell command after files and workspace are injected, before the agent launches. Useful for installing dependencies, building assets, or configuring the environment.

```python
sandbox = Sandbox(
    client="e2b",
    api_key="...",
    harness="claude-code",
    workspace=GitWorkspace(remote="https://github.com/user/repo.git"),
    setup_script="cd /workspace && npm install && npm run build",
)

await sandbox.setup()
# 1. Sandbox created, files injected
# 2. Repo cloned
# 3. "npm install && npm run build" runs
# 4. Agent starts with deps installed and assets built
```

The script runs in the workspace root. If it exits non-zero, `setup()` raises `RuntimeError` with the stderr output and the sandbox does not transition to ACTIVE.

### Custom Harness Type

```python
from harnessbox import Sandbox, HarnessTypeConfig, register_harness_type

register_harness_type(HarnessTypeConfig(
    name="my-agent",
    config_dir=".myagent",
    settings_file=None,
    hooks_dir=None,
    system_prompt_file="SYSTEM.md",
    default_dirs=("/workspace",),
    cli_command="myagent",
    cli_oneshot_template="myagent run {prompt}",
    cli_interactive_template="myagent",
))

sandbox = Sandbox(client="e2b", api_key="...", harness="my-agent")
```

## Security

HarnessBox generates Claude Code `settings.json` deny rules and a PreToolUse hook guard that protect credentials inside sandboxes:

| Threat | Defense |
|--------|---------|
| `printenv` / `env` / `os.environ` | Bash deny rules + hook guard |
| Read `.env`, `.aws/credentials` | Read deny rules |
| `WebFetch` exfiltration | Tool deny rules |
| Agent spawning sub-agents | `Agent` deny rules |
| `/proc/self/environ` | Bash deny rules + hook guard |
| IMDS credential theft (169.254.169.254) | Hook guard regex |
| Git credential helper leak | `git config credential.*` deny + Read `.git/config` deny |

```python
from harnessbox import SecurityPolicy

policy = SecurityPolicy(
    denied_tools=["WebFetch", "WebSearch", "Agent"],
    denied_bash_patterns=["rm -rf /"],
    deny_network=True,
    include_credential_guards=True,  # on by default
)
```

## Built-in Harness Types

| Harness | Config Dir | System Prompt | CLI |
|---------|-----------|---------------|-----|
| `claude-code` | `.claude` | `CLAUDE.md` | `claude --dangerously-skip-permissions ...` |
| `codex` | `.codex` | `AGENTS.md` | `codex --model o4-mini -q {prompt}` |
| `gemini-cli` | `.gemini` | `GEMINI.md` | `gemini -p {prompt}` |
| `opencode` | `.opencode` | `AGENTS.md` | `opencode -p {prompt}` |

## Comparison

| | HarnessBox | Cloudflare Artifacts | Turso AgentFS | Letta MemFS |
|---|---|---|---|---|
| **Focus** | Harness + security + workspace | Managed git repos | SQLite filesystem | Git-tracked memory |
| **Providers** | E2B, Docker, Daytona, EC2 | Cloudflare only | Turso/libSQL | Letta platform |
| **Security** | Deny rules + hooks + credential guards | Token-scoped auth | N/A | N/A |
| **Git** | Clone any remote into sandbox | Managed git protocol | N/A | Local git tracking |
| **Versioning** | Full git (branch, diff, snapshot) | Full git (fork, clone) | SQL queries | Git commits |
| **Lock-in** | None | Cloudflare Workers | Turso | Letta API |
| **Dependencies** | Zero (stdlib only) | Cloudflare SDK | Turso SDK | Letta SDK |

## API Reference

### Sandbox

```python
Sandbox(
    client: SandboxProvider | str,  # "e2b", "docker", or provider instance
    *,
    security_policy: SecurityPolicy | None = None,
    harness: str = "claude-code",
    env_vars: dict[str, str] | None = None,
    dirs: list[str] | None = None,
    files: dict[str, str] | None = None,
    timeout: int = 300,
    api_key: str | None = None,
    template: str | None = None,
    workspace: Workspace | None = None,
    setup_script: str | None = None,     # shell command to run before agent launch
)
```

**Lifecycle:** `setup()` → `run_prompt()` / `start_interactive()` → `end()` or `kill()`

### GitWorkspace

```python
GitWorkspace(
    remote: str,                          # HTTPS git remote URL
    *,
    branch: str = "main",
    commit_on_exit: bool = False,         # auto-commit + push on end()
    commit_message: str | None = None,    # default: "harnessbox: auto-commit {timestamp}"
    clone_depth: int | None = None,       # None = full clone
    auth_token: str | None = None,        # HTTPS token (never stored as env var)
    on_clone_start: Callable | None = None,
    on_clone_complete: Callable | None = None,
    on_commit: Callable | None = None,
    on_push_success: Callable | None = None,
    on_push_failure: Callable | None = None,
)
```

**Methods (called via provider):**
- `inject(provider, workspace_root)` — clone repo
- `extract(provider, workspace_root)` — commit + push (if `commit_on_exit`)
- `snapshot(provider, workspace_root, name)` — create named checkpoint
- `restore(provider, workspace_root, name)` — revert to checkpoint
- `diff(provider, workspace_root)` — unified diff since clone or last snapshot

### SecurityPolicy

```python
SecurityPolicy(
    denied_tools: list[str] = [],
    denied_bash_patterns: list[str] = [],
    deny_network: bool = False,
    include_credential_guards: bool = True,
)
```

## Project Structure

```
packages/harnessbox/
  harnessbox/
    __init__.py          # public API
    sandbox.py           # Sandbox class
    workspace.py         # Workspace protocol, GitWorkspace, MountWorkspace
    providers.py         # SandboxProvider protocol
    harness.py           # HarnessTypeConfig registry
    security.py          # SecurityPolicy, deny rules
    hooks.py             # PreToolUse hook guard
    lifecycle.py         # SessionState machine
    _setup.py            # manifest builder
    _providers/
      e2b.py             # E2B provider
      docker.py          # stub
      daytona.py         # stub
      ec2.py             # stub
  tests/                 # 211 tests
```

## License

MIT
