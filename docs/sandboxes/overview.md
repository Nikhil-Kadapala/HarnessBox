# Sandboxes

A sandbox is a secure, isolated cloud VM pre-configured with an AI coding agent. Each one has its own filesystem, network stack, and process space — completely isolated from other sandboxes via hardware-level virtualization. Think of it as a disposable development environment that boots in seconds, runs your agent, and tears down cleanly.

```python
from harnessbox import HarnessBox, WorkspaceConfig

hb = HarnessBox(provider="e2b", harness="claude-code", workspace_config=WorkspaceConfig())
session = await hb.create_session()

async for event in session.send_message("Refactor the auth module"):
    if event.delta:
        print(event.delta, end="")

await session.kill()
```

## Creating a Sandbox

```python
from harnessbox import HarnessBox, HarnessBoxSecrets, WorkspaceConfig
from harnessbox.workspace import GitRepoConfig
from harnessbox.security.policy import SecurityPolicy

hb = HarnessBox(
    provider="e2b",
    harness="claude-code",
    workspace_config=WorkspaceConfig(
        git_repo_config=GitRepoConfig(
            remote="https://github.com/org/repo.git",
            branch="feat/new-feature",
            base_branch="main",
        ),
    ),
    secrets=HarnessBoxSecrets(
        provider_api_key="your-e2b-key",
        harness_secrets={"ANTHROPIC_API_KEY": "sk-ant-..."},
        git_token="ghp_...",
    ),
    security_policy=SecurityPolicy(
        denied_tools=["computer"],
        bash_deny_patterns=["rm -rf /"],
    ),
    model="claude-sonnet-4-6-20250514",
    session_timeout=1800,
)
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `provider` | str | `"e2b"` | Sandbox provider backend |
| `harness` | str | `"claude-code"` | AI agent type to run |
| `workspace_config` | WorkspaceConfig | required | Workspace configuration; optionally contains `git_repo_config` for repository cloning |
| `secrets` | HarnessBoxSecrets | None | API keys and tokens (never stored as env vars) |
| `security_policy` | SecurityPolicy | None | Agent permission restrictions |
| `model` | str | None | Model override for the agent |
| `session_timeout` | int | 1800 | Idle timeout in seconds |

## Lifecycle

Sessions use a single ``RuntimeState`` vocabulary everywhere (SDK + HTTP):

| Status | Description |
|--------|-------------|
| `starting` | Provisioning the sandbox |
| `active` | Accepting prompts and commands |
| `paused` | Suspended to save cost; wakes on next interaction |
| `error` | Provisioning failed; can retry |
| `dead` / `ended` | Destroyed |

Sandboxes are persistent. When idle, they pause automatically to save cost. On the next `send_message()` or `run_command()`, the sandbox wakes transparently — no manual resume needed. Sessions only reach `dead` when you explicitly call `session.kill()` or `hb.kill()`.

### HTTP create (server API)

`POST /v1/workspaces/create` is a slim create surface:

- Server always mints `workspace_id` (client ids ignored); `project_id` is always `null` until a Project API exists.
- Optional `git` (+ `GitCredentials`) and `file_system` (`FileSystemParams`) — response uses `file_system_path`.
- `model` is not accepted on create (deferred to session/configure).
- Host env merge is `ENV_VAR_KEYS` setdefault only — no Claude/GCP auto-inject helpers.
- `GitCredentials.type=ssh` / `ssh_key` are accepted but not yet wired into clone auth.

```python
from harnessbox.lifecycle import RuntimeState

session = await hb.create_session()
assert session.status == RuntimeState.ACTIVE

# After idle timeout, session pauses automatically
# Next interaction wakes it transparently

await session.kill()
assert session.status == RuntimeState.DEAD
```

## Sending Prompts

Stream agent responses as typed events:

```python
from harnessbox.streaming import EventType as StreamEventType, ItemKind

async for event in session.send_message("Fix the failing test in test_auth.py"):
    match event.event_type:
        case StreamEventType.ITEM_DELTA:
            if event.item_kind == ItemKind.MESSAGE:
                print(event.delta or "", end="")
        case StreamEventType.ITEM_STARTED:
            if event.item_kind == ItemKind.TOOL_CALL:
                print(f"\n[Tool: {event.tool_kind}]")
        case StreamEventType.TURN_ENDED:
            print("\n--- Done ---")
```

Or get a single response without streaming:

```python
result = await session.send_message("What files are in /workspace?", stream=False)
print(result.text)
```

## Running Commands

Execute shell commands directly, bypassing the agent:

```python
result = await session.run_command("pytest tests/ -v")
print(result.stdout)
print(f"Exit code: {result.exit_code}")
```

## Killing a Session

```python
await session.kill()
```

If a git workspace is configured, `kill()` commits pending changes and pushes before destroying the sandbox.

## Multiple Sessions

HarnessBox supports multiple concurrent sessions:

```python
from harnessbox import HarnessBox, WorkspaceConfig
from harnessbox.workspace import GitRepoConfig

hb = HarnessBox(
    provider="e2b",
    harness="claude-code",
    workspace_config=WorkspaceConfig(
        git_repo_config=GitRepoConfig(
            remote="https://github.com/org/repo.git",
            base_branch="main",
        ),
    ),
)

auth_session = await hb.create_session(branch="feat/auth")
ui_session = await hb.create_session(branch="feat/ui")

# Work on both in parallel
await auth_session.send_message("Implement OAuth flow", stream=False)
await ui_session.send_message("Build the login page", stream=False)

# Clean up all sessions
await hb.kill()
```

## Context Manager

The context manager is a no-op on enter and calls `kill()` on exit, ensuring all sessions are cleaned up:

```python
async with HarnessBox(
    provider="e2b",
    harness="claude-code",
    workspace_config=WorkspaceConfig(),
) as hb:
    session = await hb.create_session()
    await session.send_message("Hello", stream=False)
# hb.kill() called automatically on exit — all sessions destroyed
```

## Properties

| Property | Type | Description |
|----------|------|-------------|
| `session.id` | str | Unique session identifier |
| `session.sandbox_id` | str | Provider VM identifier |
| `session.branch` | str | Git branch this session operates on |
| `session.status` | RuntimeState | Current status: `starting`, `active`, `paused`, `error`, `dead`, … |

## Related

- [Running Commands](commands.md) — Command execution details
- [Security Policies](security.md) — Restricting agent permissions
- [Streaming Events](streaming.md) — Event types and parsing
- [Git Workspaces](workspaces.md) — Repository management
- [Snapshots](snapshots.md) — Saving and forking from snapshots
