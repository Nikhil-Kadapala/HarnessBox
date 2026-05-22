# Snapshots

Snapshots capture the sandbox's full filesystem state — all sessions' workspaces, installed packages, and agent config. Running processes do not carry over; the agent must be re-launched in any sandbox forked from a snapshot.

## Saving a Snapshot

```python
snapshot = await hb.save_snapshot()
print(f"Snapshot ID: {snapshot.id}")
```

The sandbox pauses briefly during the snapshot and returns to running state. If you have multiple sessions, pass a specific session to snapshot:

```python
snapshot = await hb.save_snapshot(session=auth_session)
```

If no session is specified, the most recently created active session is used.

## Forking from a Snapshot

Create a new HarnessBox that starts with a snapshot's filesystem state:

```python
from harnessbox import HarnessBox

forked = HarnessBox.create_from_snapshot(
    snapshot_id=snapshot.id,
    harness="claude-code",
)
session = await forked.create_session()
```

The forked sandbox inherits all files, installed packages, and workspace content from the snapshot. Running processes are not preserved — create a new session to launch an agent.

## Use Cases

**Pre-built environments:** Snapshot a sandbox after installing dependencies and cloning a large repo. Fork from it to skip setup time on subsequent sessions.

```python
# One-time setup
hb = HarnessBox(provider="e2b", harness="claude-code", workspace_config=config)
session = await hb.create_session()
await session.run_command("npm install && npm run build")
snapshot = await hb.save_snapshot()

# Fast fork for each new task
worker = HarnessBox.create_from_snapshot(snapshot.id)
task_session = await worker.create_session()
async for event in task_session.send_message("Fix the auth bug"):
    print(event.text, end="")
```

**Auto-recovery:** Snapshots are created automatically before idle-timeout pause. If a sandbox dies unexpectedly (`SandboxDeadError`), the workspace manager restores from the latest snapshot transparently.

**Parallel workers:** Fork multiple sandboxes from one snapshot to run tasks in parallel, each with identical starting state but isolated execution.

## Provider Protocol

Providers implement `create_snapshot()` on the `SandboxProvider` protocol:

```python
class SandboxProvider(Protocol):
    async def create_snapshot(self) -> str:
        """Create a point-in-time snapshot and return its identifier."""
        ...

    async def create(
        self,
        env_vars: dict[str, str] | None = None,
        timeout: int = 300,
        snapshot_id: str | None = None,
    ) -> None:
        """Create a sandbox, optionally from a snapshot."""
        ...
```

When `snapshot_id` is passed to `create()`, the provider boots from that snapshot instead of a fresh template.

## Limitations

- Running processes are not preserved across snapshots. The agent must be re-launched after forking.
- Snapshot storage and retention depend on the provider (E2B manages lifecycle automatically).
- Snapshots capture entire sandbox state, not individual workspaces. For per-workspace isolation, use separate sessions with different branches.

## Related

- [Sandboxes Overview](overview.md) — Full sandbox lifecycle
- [Git Workspaces](workspaces.md) — Repository management
- [Running Commands](commands.md) — Shell access inside sandboxes
