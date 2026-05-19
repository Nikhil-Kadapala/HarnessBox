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
from harnessbox import HarnessBox, GitWorkspace

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

## How It Works

```
┌──────────────────────────────────────────────────────────────┐
│                      YOUR APPLICATION                          │
│                                                                │
│   from harnessbox import HarnessBox                           │
│   hb = HarnessBox(provider="e2b", harness="claude-code")     │
└───────────────────────────┬────────────────────────────────────┘
                            │
               ┌────────────▼────────────┐
               │       HarnessBox        │
               │                         │
               │  • Workspace lifecycle  │
               │  • Auto-pause/resume    │
               │  • Multi-session        │
               │  • Security policies    │
               └────────────┬────────────┘
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
      ┌───────────┐  ┌─────────────┐  ┌─────────────┐
      │ Session 1 │  │ Session 2   │  │ Session N   │
      │ (branch)  │  │ (branch)    │  │ (branch)    │
      │ Agent     │  │ Agent       │  │ Agent       │
      └─────┬─────┘  └──────┬──────┘  └──────┬──────┘
            │               │                 │
      ┌─────▼───────────────▼─────────────────▼──────┐
      │         E2B / Docker / Daytona / EC2         │
      └──────────────────────────────────────────────┘
```

## Server

For web applications, deploy the HarnessBox server. Same SDK, exposed over HTTP/SSE:

```bash
# Run with Docker
docker run -p 8080:8080 harnessbox/server

# Or directly
pip install "harnessbox[server]"
harnessbox serve --port 8080
```

The server provides:
- `POST /v1/workspaces` — create workspace
- `GET /v1/workspaces` — list workspaces
- `DELETE /v1/workspaces/{id}` — destroy workspace
- `POST /v1/workspaces/{id}/prompt` — send prompt (SSE stream)
- `GET /v1/workspaces/{id}/events` — subscribe to live events (SSE)

Both SDK and server use the same `HarnessBox` orchestration. Users get identical features regardless of interface.

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
from harnessbox import HarnessBox, HarnessBoxSecrets

hb = HarnessBox(
    provider="e2b",                    # Provider name or instance
    harness="claude-code",             # Agent harness type
    api_key="hb_live_...",             # Platform key (None = self-hosted)
    secrets=HarnessBoxSecrets(         # Or pass as dict
        provider_api_key="e2b_...",
        harness_secrets={"ANTHROPIC_API_KEY": "sk-ant-..."},
    ),
    model="claude-sonnet-4-6-20250514",
    system_prompt="CLAUDE.md",         # str content or Path to file
    workspace=GitWorkspace(...),
    security_policy=SecurityPolicy(...),
    setup_script="npm install",
    timeout=300,
)

# Lifecycle
sandbox_id = await hb.create()
async for event in hb.send_message("Fix tests"):
    print(event.delta)
response = await hb.send_message("Fix tests", stream=False)
result = await hb.run_command("pytest")
await hb.write_file("/workspace/f.py", "content")
content = await hb.read_file("/workspace/f.py")
await hb.kill()

# Context manager (auto create + kill)
async with HarnessBox(provider="e2b") as hb:
    async for event in hb.send_message("Hello"):
        print(event.delta)
```

### GitWorkspace

```python
GitWorkspace(
    remote: str,                          # HTTPS git remote URL
    *,
    branch: str = "main",
    base_branch: str | None = None,       # Branch to fork from
    commit_on_exit: bool = False,
    commit_message: str | None = None,
    clone_depth: int | None = None,
    auth_token: str | None = None,        # Never stored as env var
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
harnessbox/
  __init__.py                   # public API
  harnessbox.py                 # HarnessBox — sole public entry point
  workspace_manager.py          # internal workspace orchestration
  agent_manager.py              # internal agent lifecycle
  sandbox.py                    # internal sandbox orchestration
  workspace.py                  # Workspace protocol, GitWorkspace
  providers.py                  # SandboxProvider protocol
  lifecycle.py                  # WorkspaceState machine
  storage.py                    # StorageBackend protocol
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
  _storage/
    sqlite.py                   # SQLite backend
    memory.py                   # In-memory backend
tests/                          # 651 tests
```

## License

MIT
