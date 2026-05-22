# Git Workspaces

A `GitRepoConfig` defines a repository to clone into the sandbox. The workspace is injected after sandbox creation — the agent starts with the repository as its working directory.

```python
from harnessbox import HarnessBox, HarnessBoxSecrets, WorkspaceConfig
from harnessbox.workspace import GitRepoConfig

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
    secrets=HarnessBoxSecrets(git_token="ghp_your_token"),
)
```

## GitRepoConfig Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `remote` | str | required | Repository URL (HTTPS) |
| `branch` | str | None | Branch to checkout (creates if doesn't exist) |
| `clone_dir_name` | str | None | Custom directory name for the clone |
| `base_branch` | str | None | Base branch for new feature branches |

## Clone

The repository is cloned using the provider's native git API when available (faster, no git binary needed), with a shell fallback:

```python
ws = GitRepoConfig(
    remote="https://github.com/org/repo.git",
    branch="feat/auth-refactor",
    base_branch="main",
)
```

## Authentication

Git tokens are injected via `git credential helper` — never as environment variables. This prevents the agent from accidentally leaking tokens through tool calls or output.

```python
secrets = HarnessBoxSecrets(
    git_token="ghp_your_personal_access_token",
)
```

## Snapshots

Snapshots capture the sandbox's full filesystem state — all sessions' workspaces, installed packages, and agent config. Running processes do not carry over; the agent must be re-launched in any sandbox forked from a snapshot.

```python
# Save a snapshot (sandbox pauses briefly, then resumes)
snapshot = await hb.save_snapshot()

# Fork a new HarnessBox from a saved snapshot
forked = await HarnessBox.create_from_snapshot(snapshot.id)
```

Snapshots are created automatically before idle-timeout pause for internal recovery. Users can also create them on demand — the sandbox pauses briefly during the snapshot and returns to running state.

See [Snapshots](snapshots.md) for the full API.

## Branch Operations

```python
# Rename the current branch
await sandbox.rename_branch("feat/better-name")

# Get diff stats
diff = await workspace.diff_stat(provider, workspace_root)
print(f"Files changed: {diff.files_changed}")
print(f"Insertions: {diff.insertions}")
print(f"Deletions: {diff.deletions}")
```

## Create Pull Request

```python
pr = await workspace.create_pr(
    provider=provider,
    workspace_root="/workspace",
    title="feat: implement OAuth flow",
    body="Adds Google OAuth with session management",
)
print(f"PR URL: {pr.url}")
print(f"PR Number: {pr.number}")
```

## Workspace Protocol

`GitRepoConfig` implements the `Workspace` protocol. You can create custom workspace types by implementing:

```python
from harnessbox.workspace import Workspace

class CustomWorkspace(Workspace):
    async def inject(self, provider, workspace_root): ...
    async def extract(self, provider, workspace_root): ...
```

## Related

- [Sandboxes Overview](overview.md) — Full sandbox lifecycle
- [Snapshots](snapshots.md) — Saving and forking from snapshots
- [Running Commands](commands.md) — Shell access inside sandboxes
