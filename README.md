# HarnessBox

[![PyPI](https://img.shields.io/pypi/v/harnessbox)](https://pypi.org/project/harnessbox/)
[![CI](https://github.com/Nikhil-Kadapala/HarnessBox/actions/workflows/ci.yml/badge.svg)](https://github.com/Nikhil-Kadapala/HarnessBox/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)

Workspace orchestration, sandbox security, and agent lifecycle management for AI coding agents.

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

`HarnessBox` is the primary SDK entry point — provision a sandbox, inject credentials, and run an agent in three lines. Under the hood it wraps `Sandbox` (low-level orchestration) and composes cleanly with `WorkspaceManager` (pooling, auto-pause, multi-agent).

For multi-workspace orchestration with auto-pause and branch-based pooling:

```python
from harnessbox import WorkspaceManager, WorkspaceConfig, GitWorkspace

mgr = await WorkspaceManager.create(auto_pause=True, pause_timeout=1800)

config = WorkspaceConfig(
    provider="e2b",
    api_key="your-e2b-key",
    harness="claude-code",
    workspace=GitWorkspace(
        remote="https://github.com/user/repo.git",
        branch="main",
        commit_on_exit=True,
    ),
)

workspace = await mgr.get_or_create_workspace(
    remote="https://github.com/user/repo.git",
    branch="main",
    config=config,
)

async for event in mgr.prompt(workspace.workspace_id, "Fix the failing tests"):
    print(event.delta)
```

Zero runtime dependencies. Stdlib only. Provider SDKs are optional extras.

## Quickstart

```bash
pip install "harnessbox[e2b]"
```

```python
import os
from harnessbox import HarnessBox

hb = HarnessBox(
    provider="e2b",
    harness="claude-code",
    secrets={
        "provider_api_key": os.getenv("E2B_API_KEY"),
        "harness_secrets": {"ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY")},
    },
    workspace=GitWorkspace(
        remote="https://github.com/user/repo.git",
        branch="main",
        commit_on_exit=True,
    ),
)

sandbox_id = await hb.create()
async for event in hb.send_message("Fix the tests"):
    print(event.delta or "", end="")
await hb.kill()
```

## Install

```bash
pip install harnessbox

# With E2B provider
pip install "harnessbox[e2b]"
```

## What It Does

```
┌─────────────────────────────────────────────────────────────┐
│                      YOUR APPLICATION                         │
│                                                               │
│   from harnessbox import WorkspaceManager, WorkspaceConfig   │
└───────────────────────────┬───────────────────────────────────┘
                            │
               ┌────────────▼────────────┐
               │    WorkspaceManager     │
               │                         │
               │  • Branch-based pooling │  ← 87% cost savings
               │  • Auto-pause/resume    │    (reuse paused workspaces)
               │  • Multi-agent support  │
               │  • Storage backends     │
               └────────────┬────────────┘
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
      ┌───────────┐  ┌─────────────┐  ┌─────────────┐
      │ Workspace │  │ Workspace 2 │  │ Workspace N │
      │           │  │             │  │             │
      │ Sandbox   │  │  Sandbox    │  │  Sandbox    │
      │ ├ Agent 1 │  │  ├ Agent 1  │  │  └ Agent 1  │
      │ └ Agent 2 │  │  └ Agent 2  │  │             │
      └─────┬─────┘  └──────┬──────┘  └──────┬──────┘
            │               │                 │
      ┌─────▼───────────────▼─────────────────▼──────┐
      │         E2B / Docker / Daytona / EC2         │
      └──────────────────────────────────────────────┘
```

## Examples

### Branch-Based Workspace Pooling (Cost Optimization)

```python
from harnessbox import WorkspaceManager, WorkspaceConfig, GitWorkspace

mgr = await WorkspaceManager.create(auto_pause=True, pause_timeout=1800)

config = WorkspaceConfig(
    provider="e2b",
    api_key="...",
    harness="claude-code",
    workspace=GitWorkspace(
        remote="https://github.com/user/repo.git",
        branch="main",
    ),
)

# First call: creates new workspace
workspace = await mgr.get_or_create_workspace(
    remote="https://github.com/user/repo.git",
    branch="main",
    config=config,
)

async for event in mgr.prompt(workspace.workspace_id, "Add tests"):
    print(event.delta)

# Auto-pauses after 30min idle → $0/hr

# Later: reuses paused workspace (no new sandbox creation)
workspace = await mgr.get_or_create_workspace(
    remote="https://github.com/user/repo.git",
    branch="main",
    config=config,
)

async for event in mgr.prompt(workspace.workspace_id, "Fix bug"):
    print(event.delta)

# 87% cost savings for same-branch work
```

### Multiple Concurrent Agents (Same Workspace)

```python
from harnessbox import WorkspaceManager, WorkspaceConfig

mgr = await WorkspaceManager.create()

config = WorkspaceConfig(provider="e2b", api_key="...", harness="claude-code")
workspace = await mgr.create_workspace(config)

# Spawn two agents concurrently in the same workspace
import asyncio

async def agent_1():
    async for event in mgr.prompt(workspace.workspace_id, "Fix tests", conversation_id="conv-1"):
        print(f"Agent 1: {event.delta}")

async def agent_2():
    async for event in mgr.prompt(workspace.workspace_id, "Add docs", conversation_id="conv-2"):
        print(f"Agent 2: {event.delta}")

await asyncio.gather(agent_1(), agent_2())

# List active conversations
conversations = workspace.agent_manager.list_conversations()
print(conversations)  # ["conv-1", "conv-2"]
```

### Auto-Pause/Resume with Retry

```python
from harnessbox import WorkspaceManager, WorkspaceConfig

mgr = await WorkspaceManager.create(
    auto_pause=True,
    pause_timeout=1800,  # 30min idle timeout
)

config = WorkspaceConfig(provider="e2b", api_key="...", harness="claude-code")
workspace = await mgr.create_workspace(config)

async for event in mgr.prompt(workspace.workspace_id, "Make changes"):
    print(event.delta)

# After 30min idle: workspace auto-pauses → $0/hr
# Snapshot created to preserve filesystem state

# Next prompt: auto-resumes with 3 retries + exponential backoff
async for event in mgr.prompt(workspace.workspace_id, "Continue work"):
    print(event.delta)

# If sandbox expired (>7 days), recovers from snapshot transparently
```

### Storage Backends (Workspace Persistence)

```python
from harnessbox import WorkspaceManager
from harnessbox._storage.sqlite import SQLiteBackend

# SQLite backend (default: .harnessbox.db)
storage = SQLiteBackend(db_path="workspaces.db")
mgr = await WorkspaceManager.create(storage=storage)

# Workspaces survive restarts
workspace = await mgr.create_workspace(config)
print(workspace.workspace_id)  # "abc-123"

# After restart: load from storage
mgr2 = await WorkspaceManager.create(storage=SQLiteBackend("workspaces.db"))
workspace = mgr2.get_workspace("abc-123")
print(workspace.status)  # "paused" or "active"

# Pooling works across restarts
workspace = await mgr2.get_or_create_workspace(
    remote="https://github.com/user/repo.git",
    branch="main",
    config=config,
)  # Resumes paused workspace from storage
```

### HTTP Server (SSE Streaming)

```python
from harnessbox import WorkspaceManager
from harnessbox.server import create_app

# Create server
mgr = await WorkspaceManager.create(auto_pause=True)
app = create_app(mgr)

# Endpoints:
# POST   /v1/workspaces                      — create workspace
# GET    /v1/workspaces                      — list workspaces
# GET    /v1/workspaces/{id}                 — get workspace info
# DELETE /v1/workspaces/{id}                 — destroy workspace
# POST   /v1/workspaces/{id}/prompt          — send prompt (SSE stream)
# GET    /v1/workspaces/{id}/conversations   — list conversations

# Run server
import uvicorn
uvicorn.run(app, host="0.0.0.0", port=8080)
```

**Client example:**
```python
import requests

# Create workspace
resp = requests.post("http://localhost:8080/v1/workspaces", json={
    "provider": "e2b",
    "harness": "claude-code",
})
workspace_id = resp.json()["workspace_id"]

# Send prompt (SSE stream)
resp = requests.post(
    f"http://localhost:8080/v1/workspaces/{workspace_id}/prompt",
    json={"prompt": "Fix the tests"},
    stream=True,
)

for line in resp.iter_lines():
    if line:
        print(line.decode())
```

### Low-Level Sandbox API (Direct Control)

If you need direct sandbox control without WorkspaceManager orchestration:

```python
from harnessbox import Sandbox, SecurityPolicy, GitWorkspace

sandbox = Sandbox(
    client="e2b",
    api_key="...",
    harness="claude-code",
    security_policy=SecurityPolicy(
        denied_tools=["WebFetch", "WebSearch", "Agent"],
        deny_network=True,
    ),
    workspace=GitWorkspace(
        remote="https://github.com/user/repo.git",
        commit_on_exit=True,
    ),
    setup_script="npm install && npm run build",
)

await sandbox.setup()
# 1. Sandbox created, files injected
# 2. Repo cloned
# 3. "npm install && npm run build" runs
# 4. Agent ready

async for line in sandbox.run_prompt("Fix the tests"):
    print(line)

await sandbox.end()  # commits + pushes changes
```

The low-level `Sandbox` API gives you full control but no auto-pause, pooling, or multi-agent support. Use `WorkspaceManager` for production workloads.

### Workspace Lifecycle Transitions

```python
from harnessbox import WorkspaceManager, WorkspaceState

mgr = await WorkspaceManager.create()
workspace = await mgr.create_workspace(config)

# STARTING → ACTIVE (auto-transition after setup)
print(workspace.status)  # "active"

# ACTIVE → PAUSED (manual or auto after 30min idle)
await mgr._pause_workspace(workspace.workspace_id)
print(workspace.status)  # "paused"

# PAUSED → ACTIVE (auto-resume on next prompt)
async for event in mgr.prompt(workspace.workspace_id, "Continue"):
    print(event.delta)
print(workspace.status)  # "active"

# ACTIVE → ENDING → MERGED/FAILED (via transition_workspace)
await mgr.transition_workspace(workspace.workspace_id, WorkspaceState.ENDING)
# ... commit + push logic runs ...
await mgr.transition_workspace(workspace.workspace_id, WorkspaceState.MERGED)
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
| `opencode` | `.opencode` | `AGENTS.md` | `opencode -p {prompt}` |

## Key Features

| Feature | Description | Benefit |
|---------|-------------|---------|
| **Branch-based pooling** | Reuses paused workspaces for same (remote, branch) | 87% cost savings for same-branch work |
| **Auto-pause/resume** | Idle workspaces pause after 30min → $0/hr | Transparent resume with retry + snapshot recovery |
| **Multi-agent support** | Multiple concurrent agents per workspace | Parallel workflows without git conflicts (user's responsibility) |
| **Storage backends** | SQLite or in-memory persistence | Workspaces survive restarts, pool works across sessions |
| **Lazy agent spawning** | Agents spawn on first prompt | No upfront cost for unused conversations |
| **Snapshot recovery** | E2B snapshots preserve filesystem state | Recover from expired sandboxes (>7 days) |
| **HTTP/SSE server** | Starlette endpoints + event streaming | Production-ready API with SSE event replay |
| **Zero dependencies** | Stdlib only at runtime | Provider SDKs are optional extras |

## Comparison

| | HarnessBox v1.0 | Cloudflare Artifacts | Turso AgentFS | Letta MemFS |
|---|---|---|---|---|
| **Focus** | Workspace orchestration + pooling + multi-agent | Managed git repos | SQLite filesystem | Git-tracked memory |
| **Cost optimization** | Auto-pause ($0/hr) + pooling (87% savings) | Always-on | N/A | N/A |
| **Providers** | E2B, Docker, Daytona, EC2 | Cloudflare only | Turso/libSQL | Letta platform |
| **Multi-agent** | Concurrent agents per workspace | No | N/A | No |
| **Storage** | SQLite/in-memory backends | Cloudflare Durable Objects | libSQL | Local files |
| **Git** | Clone any remote, commit/push on exit | Managed git protocol | N/A | Local git tracking |
| **Lock-in** | None | Cloudflare Workers | Turso | Letta API |
| **Dependencies** | Zero (stdlib only) | Cloudflare SDK | Turso SDK | Letta SDK |

## API Reference

### HarnessBox (Primary SDK Entry Point)

```python
from harnessbox import HarnessBox, HarnessBoxSecrets

hb = HarnessBox(
    provider="e2b",                    # Sandbox provider
    harness="claude-code",             # Agent harness type
    api_key="hb_live_...",             # Platform key (None = self-hosted)
    secrets=HarnessBoxSecrets(         # Or pass as dict
        provider_api_key="e2b_...",
        harness_secrets={"ANTHROPIC_API_KEY": "sk-ant-..."},
    ),
    model="claude-sonnet-4-6-20250514",  # Override default model
    system_prompt="CLAUDE.md",         # str content or Path
    workspace=GitWorkspace(...),       # Git workspace to clone
    security_policy=SecurityPolicy(...),
    setup_script="npm install",
    timeout=300,
)

# Lifecycle
sandbox_id = await hb.create()         # Provision sandbox
async for event in hb.send_message("Fix tests"):  # Stream events
    print(event.delta)
response = await hb.send_message("Fix tests", stream=False)  # Await response
result = await hb.run_command("pytest")  # Run shell command
await hb.write_file("/workspace/f.py", "content")
content = await hb.read_file("/workspace/f.py")
await hb.kill()                        # Destroy sandbox

# Context manager (auto create + kill)
async with HarnessBox(provider="e2b") as hb:
    async for event in hb.send_message("Hello"):
        print(event.delta)
```

### WorkspaceManager

```python
class WorkspaceManager:
    @classmethod
    async def create(
        cls,
        storage: StorageBackend | None = None,
        *,
        auto_pause: bool = True,
        pause_timeout: int = 1800,  # seconds (default 30min)
    ) -> WorkspaceManager: ...

    async def create_workspace(
        self,
        config: WorkspaceConfig,
        *,
        workspace_id: str | None = None,
    ) -> WorkspaceInstance: ...

    async def get_or_create_workspace(
        self,
        remote: str,
        branch: str,
        *,
        config: WorkspaceConfig | None = None,
    ) -> WorkspaceInstance: ...

    def get_workspace(self, workspace_id: str) -> WorkspaceInstance: ...

    def list_workspaces(self) -> list[WorkspaceInstance]: ...

    async def destroy_workspace(self, workspace_id: str) -> None: ...

    async def prompt(
        self,
        workspace_id: str,
        prompt: str,
        *,
        conversation_id: str | None = None,
    ) -> AsyncGenerator[UniversalEvent, None]: ...

    async def transition_workspace(
        self,
        workspace_id: str,
        target_state: WorkspaceState,
    ) -> None: ...

    async def shutdown_all(self) -> None: ...
```

**Key methods:**
- `get_or_create_workspace()` — Pool hit/miss logic, resumes paused workspace if found
- `prompt()` — Auto-resumes if paused, spawns agent lazily, streams events
- Auto-pause background task scans every 60s for idle workspaces

### WorkspaceConfig

```python
@dataclass
class WorkspaceConfig:
    provider: str = "e2b"
    api_key: str | None = None
    template: str | None = None
    harness: str = "claude-code"
    security_policy: SecurityPolicy | None = None
    workspace: Workspace | None = None
    setup_script: str | None = None
    timeout: int = 300
    env_vars: dict[str, str] | None = None
    dirs: list[str] | None = None
    files: dict[str, str] | None = None
```

### WorkspaceInstance

```python
@dataclass
class WorkspaceInstance:
    workspace_id: str
    remote: str
    branch: str
    provider: str
    provider_sandbox_id: str | None
    snapshot_id: str | None
    status: str  # "active", "paused", "starting", "ending", "merged", "failed"
    created_at: str
    last_active: str
    sandbox: Sandbox | None = None
    agent_manager: AgentManager | None = None
```

### Sandbox (Low-Level API)

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
    setup_script: str | None = None,
    event_handler: EventHandler | None = None,
)
```

**Lifecycle:** `setup()` → `run_prompt()` / `start_interactive()` → `end()` or `kill()`

Use `WorkspaceManager` for production workloads. `Sandbox` is for direct control without orchestration.

### AgentManager (Per-Workspace)

```python
class AgentManager:
    def __init__(self, sandbox: Sandbox) -> None: ...

    async def run_prompt(
        self,
        conversation_id: str,
        prompt: str,
        harness: str = "claude-code",
    ) -> AsyncGenerator[UniversalEvent, None]: ...

    def list_conversations(self) -> list[str]: ...

    async def terminate_agent(self, conversation_id: str) -> None: ...

    async def shutdown_all(self) -> None: ...
```

Agents are lazily spawned on first prompt. Multiple concurrent agents per workspace are supported.

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

### StorageBackend (Protocol)

```python
class StorageBackend(Protocol):
    async def initialize(self) -> None: ...

    async def save_workspace(self, record: dict[str, Any]) -> None: ...
    async def get_workspace(self, workspace_id: str) -> dict[str, Any] | None: ...
    async def update_workspace(self, workspace_id: str, **fields: Any) -> None: ...
    async def list_workspaces(
        self,
        *,
        status: str | None = None,
        remote: str | None = None,
        branch: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]: ...
    async def delete_workspace(self, workspace_id: str) -> None: ...

    async def save_conversation(self, record: dict[str, Any]) -> None: ...
    async def get_conversations(self, workspace_id: str) -> list[dict[str, Any]]: ...
    async def update_conversation(self, conversation_id: str, **fields: Any) -> None: ...
```

**Built-in backends:**
- `SQLiteBackend` — persistent (default: `.harnessbox.db`)
- `MemoryBackend` — ephemeral (in-memory dict)

## Project Structure

```
harnessbox/
  __init__.py                   # public API
  harnessbox.py                 # HarnessBox — primary SDK entry point
  workspace_manager.py          # WorkspaceManager, WorkspaceInstance, WorkspaceConfig
  agent_manager.py              # AgentManager (lazy agent spawning)
  sandbox.py                    # Sandbox class (internal orchestration)
  workspace.py                  # Workspace protocol, GitWorkspace
  providers.py                  # SandboxProvider protocol
  lifecycle.py                  # WorkspaceState machine
  storage.py                    # StorageBackend protocol
  streaming.py                  # UniversalEvent, StreamParser
  events.py                     # EventBuffer (SSE replay)
  server.py                     # HTTP/SSE transport (Starlette)
  config/
    harness.py                  # HarnessTypeConfig registry
    manifest.py                 # SandboxManifest builder
  security/
    policy.py                   # SecurityPolicy, deny rules
    hooks.py                    # PreToolUse hook guard
    events.py                   # SandboxEvent, EventHandler
  _providers/
    e2b.py                      # E2B provider
    docker.py                   # stub
  _storage/
    sqlite.py                   # SQLite backend
    memory.py                   # In-memory backend
tests/                          # 649 tests
```

## License

MIT
