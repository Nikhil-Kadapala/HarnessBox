# Quickstart

## Prerequisites

The HarnessBox SDK installed with E2B extras, and an E2B API key.

```bash
pip install harnessbox[e2b]
export E2B_API_KEY=your-e2b-api-key
```

## Create Your First Sandbox

```python
import asyncio
from harnessbox import HarnessBox, WorkspaceConfig

async def main():
    hb = HarnessBox(
        provider="e2b",
        harness="claude-code",
        workspace_config=WorkspaceConfig(),
    )
    session = await hb.create_session()
    print(f"session {session.id} on sandbox {session.sandbox_id}")

    # Send a prompt and stream the agent's response
    async for event in session.send_message("echo 'Hello from HarnessBox!'"):
        if event.delta:
            print(event.delta, end="")

    await session.kill()

asyncio.run(main())
```

Sessions stay alive as long as you need them. They don't shut down after a single prompt — you can keep sending messages, running commands, and iterating for hours. Sessions only stop when you explicitly kill them or when the idle timeout expires (default 30 minutes, configurable).

## Run a Command Directly

You can also run shell commands without going through the agent:

```python
result = await session.run_command("ls -la /workspace")
print(result.stdout)
print(f"Exit code: {result.exit_code}")
```

## With a Git Workspace

Clone a repository into the sandbox automatically:

```python
from harnessbox import HarnessBox, HarnessBoxSecrets, WorkspaceConfig
from harnessbox.workspace import GitRepoConfig

hb = HarnessBox(
    provider="e2b",
    harness="claude-code",
    workspace_config=WorkspaceConfig(
        git_repo_config=GitRepoConfig(
            remote="https://github.com/your-org/your-repo.git",
            branch="feat/new-feature",
            base_branch="main",
        ),
    ),
    secrets=HarnessBoxSecrets(
        provider_api_key="your-e2b-key",
        harness_secrets={"ANTHROPIC_API_KEY": "sk-ant-..."},
    ),
)
```

The repo is cloned into the sandbox's user workspace at usr/workspace/, and the agent starts with that repo root as its working directory.

## Next Steps

- [How It Works](how-it-works.md) — Architecture and lifecycle
- [Sandboxes Overview](../sandboxes/overview.md) — Full sandbox API
- [Running Commands](../sandboxes/commands.md) — Command execution details
- [Security Policies](../sandboxes/security.md) — Control agent permissions
