# HarnessBox

[![PyPI](https://img.shields.io/pypi/v/harnessbox)](https://pypi.org/project/harnessbox/)
[![CI](https://github.com/Nikhil-Kadapala/HarnessBox/actions/workflows/ci.yml/badge.svg)](https://github.com/Nikhil-Kadapala/HarnessBox/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)

Run AI coding agents in secure sandbox environments with workspace orchestration, auto-pause, and multi-session support.

```python
import os
from harnessbox import HarnessBox

async with HarnessBox(
    provider="e2b",
    harness="claude-code",
    secrets={
        "provider_api_key": os.getenv("E2B_API_KEY"),
        "harness_secrets": {"ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY")},
    },
) as hb:
    async for event in hb.send_message("Fix the failing test"):
        print(event.delta or "", end="")
```

`HarnessBox` is the sole public API — provision sandboxes, manage workspaces, run agent sessions. Zero runtime dependencies.

## Install

```bash
pip install harnessbox

# With E2B provider
pip install "harnessbox[e2b]"
```

## Quickstart

```python
import os
from harnessbox import HarnessBox, WorkspaceConfig
from harnessbox.workspace import GitRepoConfig

hb = HarnessBox(
    provider="e2b",
    harness="claude-code",
    workspace_config=WorkspaceConfig(
        git_repo_config=GitRepoConfig(
            remote="https://github.com/user/repo.git",
            branch="main",
        ),
    ),
    secrets={
        "provider_api_key": os.getenv("E2B_API_KEY"),
        "harness_secrets": {"ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY")},
    },
)

session = await hb.create_session()
async for event in session.send_message("Fix the tests"):
    print(event.delta or "", end="")
await hb.kill()
```

## Multi-Session Mode

Run multiple agents on different branches simultaneously:

```python
import os
from harnessbox import HarnessBox, WorkspaceConfig, WorkspaceMode
from harnessbox.workspace import GitRepoConfig

hb = HarnessBox(
    provider="e2b",
    harness="claude-code",
    workspace_config=WorkspaceConfig(
        workspace_mode=WorkspaceMode.NEW,
        git_repo_config=GitRepoConfig(
            remote="https://github.com/user/repo.git",
            branch="main",
        ),
    ),
    secrets={
        "provider_api_key": os.getenv("E2B_API_KEY"),
        "harness_secrets": {"ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY")},
    },
)

# Each session gets its own sandbox
auth_session = await hb.create_session(branch="feat/auth")
ui_session = await hb.create_session(branch="feat/ui")

# Interact with sessions directly
async for event in auth_session.send_message("Fix the auth bug"):
    print(event.delta or "", end="")

# Non-streaming
result = await ui_session.send_message("Add dark mode", stream=False)
print(result.text)

# Clean up
await auth_session.kill()
await ui_session.kill()
```

See [`examples/multi_session.py`](packages/sdk/examples/multi_session.py) for a complete runnable example.

## How It Works

HarnessBox is a Python library. You import it, provision a sandbox, and stream agent output. That's the whole product.

```python
from harnessbox import HarnessBox, WorkspaceConfig
from harnessbox.workspace import GitRepoConfig

hb = HarnessBox(
    provider="e2b",
    harness="claude-code",
    workspace_config=WorkspaceConfig(
        git_repo_config=GitRepoConfig(
            remote="https://github.com/user/repo.git",
        )
    ),
    secrets={...}
)
session = await hb.create_session()

async for event in session.send_message("Fix the failing test"):
    print(event.delta or "", end="")

await hb.kill()
```

Everything else is a deployment choice:

```
┌────────────────────────────────────────────────────────────┐
│              HarnessBox (Python SDK)                         │
│                                                             │
│  • Create workspaces and sessions                          │
│  • Stream agent output as async events                     │
│  • Auto-pause idle sandboxes, resume on next message       │
│  • Persist state across restarts (SQLite)                  │
│  • Security policies, credential guards                    │
└─────────────────────┬───────────────────┬──────────────────┘
                      │                   │
        "I'm a script │                   │ "I need a web UI
        or service"   │                   │  or team access"
                      ▼                   ▼
           ┌─────────────────┐  ┌────────────────────────────┐
           │  Use the SDK    │  │  Run `harnessbox serve`    │
           │  directly       │  │  (same SDK + HTTP/SSE)     │
           │                 │  │                            │
           │  No server.     │  │  Adds: multi-client,      │
           │  No infra.      │  │  web dashboard, shared    │
           │  Just Python.   │  │  state across consumers.  │
           └─────────────────┘  └────────────────────────────┘
```

Think of it like SQLite vs Postgres. SQLite is embedded — no server, works great for one process. Postgres adds a server for shared access. Same SQL, same data model, different deployment. HarnessBox works the same way.

**When you don't need the server:**
- Scripts and CI pipelines
- Single-developer tools
- Programmatic agents (backend services)
- Anything where one Python process is enough

**When you add the server:**
- You're building a web UI for your team
- Multiple clients (web + CLI + SDK) need to see the same workspaces
- You want an always-on orchestrator that survives process restarts
- You're running our hosted platform (`base_url="https://api.harnessbox.dev"`)

## Server

The server is the SDK running as a long-lived process that accepts HTTP connections. Same features, accessible over the network.

```bash
# Self-hosted
pip install "harnessbox[server]"
harnessbox serve --port 8080

# Or with Docker
docker run -p 8080:8080 harnessbox/server
```

Point the SDK at your server (planned):

```python
# SDK becomes a thin client — all orchestration happens server-side
hb = HarnessBox(base_url="http://localhost:8080", secrets={...})
# Same API, same streaming, same everything
```

Server endpoints:
- `POST /v1/workspaces` — create workspace
- `GET /v1/workspaces` — list workspaces
- `DELETE /v1/workspaces/{id}` — destroy workspace
- `POST /v1/workspaces/{id}/prompt` — send prompt (SSE stream)
- `GET /v1/workspaces/{id}/events` — subscribe to live events (SSE)

## Security

HarnessBox generates agent-specific deny rules and PreToolUse hook guards that protect credentials inside sandboxes:

| Threat | Defense |
|--------|---------|
| `printenv` / `env` / `os.environ` | Bash deny rules + hook guard |
| Read `.env`, `.aws/credentials` | Read deny rules |
| `WebFetch` exfiltration | Tool deny rules |
| Agent spawning sub-agents | `Agent` deny rules |
| `/proc/self/environ` | Bash deny rules + hook guard |
| IMDS credential theft (169.254.169.254) | Hook guard regex |
| Git credential helper leak | `git config credential.*` deny |

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
| `opencode` | `.opencode` | `AGENTS.md` | `opencode -p {prompt}` |

## Key Features

| Feature | Description |
|---------|-------------|
| **Auto-pause/resume** | Idle workspaces pause → $0/hr. Resume transparently on next message. |
| **Multi-session** | Multiple concurrent agent sessions per workspace. |
| **Branch-based pooling** | Same (remote, branch) reuses existing workspace. |
| **Security policies** | Credential guards, tool deny lists, network blocking. |
| **Git workflows** | Clone, commit, push on exit. Branch creation from base. |
| **Zero dependencies** | Stdlib only at runtime. Provider SDKs are optional extras. |
| **Any provider** | E2B, Docker, Daytona, EC2. Protocol-based extensibility. |

## API Reference

### HarnessBox

```python
from harnessbox import HarnessBox, HarnessBoxSecrets, WorkspaceConfig, WorkspaceMode
from harnessbox.workspace import GitRepoConfig

hb = HarnessBox(
    provider="e2b",                    # Provider name or instance
    harness="claude-code",             # Agent harness type
    api_key="hb_live_...",             # Platform key (None = self-hosted)
    secrets=HarnessBoxSecrets(         # Or pass as dict
        provider_api_key="e2b_...",
        harness_secrets={"ANTHROPIC_API_KEY": "sk-ant-..."},
    ),
    model="claude-sonnet-4-6-20250514",
    system_prompt=Path("CLAUDE.md"),    # Path to load from file, or str for inline content
    workspace_config=WorkspaceConfig(
        workspace_mode=WorkspaceMode.NEW,
        git_repo_config=GitRepoConfig(
            remote="https://github.com/org/repo.git",
            branch="feat/auth",
            base_branch="main",
        ),
    ),
    security_policy=SecurityPolicy(...),
    setup_script="npm install",
    timeout=300,
)

# Lifecycle
session = await hb.create_session()
async for event in session.send_message("Fix tests"):
    print(event.delta)

# Non-streaming
response = await session.send_message("Fix tests", stream=False)

# Run a raw shell command in the session
result = await session.run_command("pytest")

# Clean up all sessions
await hb.kill()

# Context manager (auto create + kill)
async with HarnessBox(provider="e2b", workspace_config=WorkspaceConfig()) as hb:
    session = await hb.create_session()
    async for event in session.send_message("Hello"):
        print(event.delta)
```

### WorkspaceConfig

```python
WorkspaceConfig(
    workspace_mode: WorkspaceMode = WorkspaceMode.NEW, # NEW or SHARED
    git_repo_config: GitRepoConfig | None = None,      # Git repo setup
    file_system_config: FileSystemConfig | None = None,# Local directory mapping
)
```

### GitRepoConfig

```python
GitRepoConfig(
    remote: str,                          # Git remote HTTPS or SSH URL
    *,
    branch: str = "main",                 # Checkout branch
    base_branch: str | None = None,       # Base branch to fork from
    clone_depth: int | None = None,       # Git shallow clone depth
    auth_token: str | None = None,        # Git access token for auth
    clone_dir_name: str | None = None,    # Custom name for directory
)
```

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
packages/sdk/src/harnessbox/
  __init__.py                   # public API
  harnessbox.py                 # HarnessBox — public entry point
  sandbox.py                    # internal sandbox orchestration
  workspace.py                  # Workspace protocol, GitRepoConfig
  providers.py                  # SandboxProvider protocol
  lifecycle.py                  # SessionStatus & RuntimeState transition map
  streaming.py                  # UniversalEvent, StreamParser
  events.py                     # EventBuffer (SSE replay)
  server.py                     # HTTP/SSE transport
  config/
    harness.py                  # HarnessTypeConfig registry
    manifest.py                 # SandboxManifest builder
  security/
    policy.py                   # SecurityPolicy, deny rules
    hooks.py                    # PreToolUse hook guard
    events.py                   # SandboxEvent, EventHandler
  _providers/
    e2b.py                      # E2B provider
  _server/
    workspace_manager.py        # internal workspace orchestration
    registry.py                 # workspace registry
    _storage/
      sqlite.py                 # SQLite backend
      memory.py                 # In-memory backend
packages/sdk/tests/             # Unit & integration tests
apps/web/                       # Web application front-end (Vite/React)
apps/api/                       # Cloud API for paid tier (planned)
```

## License

MIT
