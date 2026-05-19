# HarnessBox Domain Language

## Core Concepts

**Sandbox** — A cloud VM instance (E2B, Docker, Daytona). The compute unit. One sandbox = one isolated Linux environment with filesystem, network, and installed tools.

**Workspace** — A sandbox bound to a git repository. The logical unit that HarnessBox manages. A workspace has a mode (SHARED or NEW) that determines how sessions relate to sandboxes.

**Session** — An agent conversation within a workspace. Each session = one agent process (Claude Code, Codex, etc.) + one branch or worktree. Sessions are the unit users interact with.

**HarnessBox** — The orchestrator. Creates workspaces, manages sessions, handles lifecycle (pause/resume/kill). The sole public API surface for both SDK and server consumers.

## Workspace Modes

**SHARED mode** — One sandbox, one cloned repo, multiple sessions. Each session gets its own git worktree (`git worktree add`) within the shared sandbox. Agents share filesystem (installed tools, dependencies) and can read each other's worktrees (intentional — enables cross-branch awareness). Sessions run as independent agent processes concurrently.

**NEW mode** — Each session gets its own sandbox with its own git clone on a dedicated branch. Full isolation between sessions. No shared state.

## Hierarchy

```
HarnessBox (orchestrator)
└── Workspace (sandbox + git repo config + mode)
    ├── Session 1 (agent process + branch/worktree)
    ├── Session 2 (agent process + branch/worktree)
    └── Session N
```

In SHARED mode: Workspace has 1 sandbox, N sessions share it via worktrees.
In NEW mode: Workspace has N sandboxes, one per session.

## Lifecycle

- Workspaces auto-pause after idle timeout (no active sessions).
- Paused workspaces resume on next session interaction.
- Sessions are provisioned eagerly (sandbox created immediately on session creation, not on first message).

## Boundaries

- `Sandbox` and `SandboxProvider` are internal implementation details (provider layer).
- `WorkspaceManager` is an internal orchestration detail (server layer).
- Users interact only with `HarnessBox`, `Session`, and configuration types.
