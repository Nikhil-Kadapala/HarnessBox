---
type: Guide
title: Introduction
description: What HarnessBox is and how to install the SDK.
tags: [sdk, agent, sandbox]
status: stable
generated: { by: process:okf-migration, at: 2026-07-27T19:33:00Z }
---
# Introduction

HarnessBox gives you secure, sandboxed environments for running AI coding agents. Each sandbox is an isolated cloud VM with its own filesystem, network, and process space — pre-configured with an AI agent (Claude Code, Codex, etc.), security policies, and an optional git workspace. Provision a sandbox, send prompts, stream agent output, and tear it down — all from a single Python SDK.

## Secure by default

Hardware-isolated VMs via E2B. Security policies control which tools the agent can use, what files it can read, and what commands it can run.

## Multi-agent support

Claude Code, Codex, and custom harnesses. Each harness type defines how the agent is invoked, configured, and monitored.

## Git-native workspaces

Clone a repo, branch, run the agent, then commit and push — all within the sandbox lifecycle. Checkpoints let you snapshot and restore.

## Provider-agnostic

The `SandboxProvider` protocol means you can swap E2B for another VM backend without changing application code.

## Install

```bash
pip install harnessbox
```

This includes the SDK, interactive CLI (`hbox`), and local server deps. For E2B sandboxes:

```bash
pip install harnessbox[e2b]
```

Set your provider credentials:

```bash
export E2B_API_KEY=your-e2b-api-key
```

## Quick Example

```python
from harnessbox import HarnessBox, WorkspaceConfig

async with HarnessBox(
    provider="e2b",
    harness="claude-code",
    workspace_config=WorkspaceConfig(),
) as hb:
    session = await hb.create_session()

    async for event in session.send_message("Write a hello world script"):
        if event.delta:
            print(event.delta, end="")

    await session.kill()
```

## Next Steps

- [Quickstart](quickstart.md) — Create your first sandbox in 2 minutes
- [How It Works](how-it-works.md) — Architecture: providers, harnesses, security
- [Sandboxes](../sandboxes/overview.md) — The compute primitive
- [Security Policies](../sandboxes/security.md) — Control what agents can do
