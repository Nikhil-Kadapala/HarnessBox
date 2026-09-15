# HarnessBox Domain Language

## Core Concepts

**Sandbox** — A cloud VM instance (E2B, Docker, Daytona). The compute unit. One sandbox = one isolated Linux environment with filesystem, network, and installed tools.

**Project** — A locally persisted record for a source repository. It stores the repository remote and default branch; creating a Project does not provision a runtime or create a Workspace.

**Workspace** — The durable logical computer HarnessBox manages: a repository/branch, workspace configuration, and a replaceable binding to a sandbox. A workspace can outlive a sandbox id when HarnessBox recovers it from a snapshot.

**Conversation** — A durable agent chat thread within a workspace. Each conversation has its own harness type, native agent session id, and live agent process when active. Multiple conversations can execute concurrently against the same workspace filesystem.

**Session** — The user-facing agent interaction associated with a Workspace. Its identity is independent of branch names, worktree paths, and provider sandbox IDs. In server internals, durable chat threads are called Conversations to distinguish them from workspace/runtime lifecycle.

**HarnessBox** — The orchestrator. Creates workspaces, routes conversations, and handles lifecycle (pause/resume/kill). The sole public API surface for both SDK and server consumers.

## Conversation Concurrency

One workspace can run multiple conversations and harnesses in parallel inside the same sandbox. They intentionally share the same checkout, branch, filesystem, network namespace, and installed tools.

HarnessBox serializes turns only within the same conversation. It does not serialize, isolate, detect, or reconcile file edits and Git operations across different conversations. Callers are responsible for coordinating concurrent work when agents touch overlapping files or repository state.

This is a product contract, not an implementation detail. Workspace lifecycle operations still coordinate sandbox pause, recovery, and destruction, but must not impose whole-turn serialization across otherwise independent conversations.

## Hierarchy

```
HarnessBox (orchestrator; local durable storage)
└── Project (repository remote + default branch)
    └── Workspace (durable branch/config + replaceable cloud runtime binding)
        └── Session / Conversation (stable agent-thread identity)
```

Project, Workspace, Session/Conversation metadata, and events are persisted by the local HarnessBox server. Agent processes and their filesystems run in a cloud runtime selected through the provider adapter. Branch/worktree and provider sandbox IDs are workspace environment/state, not session identity. The live process map is replaceable runtime state; a recovered workspace keeps its `workspace_id` and conversation ids while its provider sandbox ID may change.

## Lifecycle

- Workspaces auto-pause after idle timeout when no conversation turns are active.
- Paused workspaces resume on the next interaction.
- Pause, snapshot, recovery, and destruction coordinate with all active turns; ordinary turns in different conversations remain eligible to execute concurrently.

## Boundaries

- `Sandbox` and `SandboxProvider` are internal implementation details (provider layer).
- `WorkspaceManager` is an internal orchestration detail (server layer).
- SDK users interact with `HarnessBox`, `Session`, and configuration types. HTTP clients address a Workspace and optionally select a Conversation.

## External Framework Review

The review of [Omnigent](https://github.com/omnigent-ai/omnigent), [Omnara](https://github.com/omnara-ai/omnara), and [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) concluded that HarnessBox should adopt specific patterns, not replace its core domain model with another framework.

- Keep the `Project → Workspace → Session/Conversation` hierarchy. It is narrower and better aligned with HarnessBox than the broader external control planes.
- Adopt an Omnigent-style harness adapter registry so Claude Code, Codex, and future harnesses share a stable lifecycle and streaming boundary.
- Adopt Omnara-style durable state handling: atomically persist lifecycle state, turn boundaries, native agent session ids, and events so agents can resume after crashes or machine replacement.
- Keep the existing sandbox provider protocol, adding provider registration and capability discovery without importing a full provider ecosystem.
- Add a small optional plugin interface inspired by DeepSeek Harness for harnesses, tools, storage, and lifecycle hooks. Do not make the runtime depend on DeepSeek Harness or Cordis; DeepSeek Harness is a developer preview with compatibility-breaking changes.
- Do not adopt the external projects' web UIs, CLIs, authentication, RBAC, cloud control planes, or broad model/provider marketplaces in the current slice.

Recommended implementation order: harness adapter boundary first, durable event/state persistence second, and optional plugin hooks later.
