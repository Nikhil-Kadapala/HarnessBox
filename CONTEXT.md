# HarnessBox Domain Language

## Core Concepts

**Sandbox** — A cloud VM instance (E2B, Docker, Daytona). The compute unit. One sandbox = one isolated Linux environment with filesystem, network, and installed tools.

**Workspace** — The durable logical computer HarnessBox manages: a repository/branch, workspace configuration, and a replaceable binding to a sandbox. A workspace can outlive a sandbox id when HarnessBox recovers it from a snapshot.

**Conversation** — A durable agent chat thread within a workspace. Each conversation has its own harness type, native agent session id, and live agent process when active. Multiple conversations can execute concurrently against the same workspace filesystem.

**Session** — The public SDK interaction handle. In the server architecture, durable chat threads are called Conversations so they are not confused with sandbox or workspace lifecycle.

**HarnessBox** — The orchestrator. Creates workspaces, routes conversations, and handles lifecycle (pause/resume/kill). The sole public API surface for both SDK and server consumers.

## Conversation Concurrency

One workspace can run multiple conversations and harnesses in parallel inside the same sandbox. They intentionally share the same checkout, branch, filesystem, network namespace, and installed tools.

HarnessBox serializes turns only within the same conversation. It does not serialize, isolate, detect, or reconcile file edits and Git operations across different conversations. Callers are responsible for coordinating concurrent work when agents touch overlapping files or repository state.

This is a product contract, not an implementation detail. Workspace lifecycle operations still coordinate sandbox pause, recovery, and destruction, but must not impose whole-turn serialization across otherwise independent conversations.

## Hierarchy

```
HarnessBox (orchestrator)
└── Workspace (durable repo/branch + current sandbox binding)
    ├── Conversation 1 (harness + native session id + live process)
    ├── Conversation 2 (harness + native session id + live process)
    └── Conversation N
```

The live process map is replaceable runtime state. Conversation metadata is durable, and a recovered workspace keeps the same `workspace_id` and conversation ids while its `provider_sandbox_id` may change.

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

- Keep the `Project → Workspace → Conversation` hierarchy. It is narrower and better aligned with HarnessBox than the broader external control planes.
- Adopt an Omnigent-style harness adapter registry so Claude Code, Codex, and future harnesses share a stable lifecycle and streaming boundary.
- Adopt Omnara-style durable state handling: atomically persist lifecycle state, turn boundaries, native agent session ids, and events so agents can resume after crashes or machine replacement.
- Keep the existing sandbox provider protocol, adding provider registration and capability discovery without importing a full provider ecosystem.
- Add a small optional plugin interface inspired by DeepSeek Harness for harnesses, tools, storage, and lifecycle hooks. Do not make the runtime depend on DeepSeek Harness or Cordis; DeepSeek Harness is a developer preview with compatibility-breaking changes.
- Do not adopt the external projects' web UIs, CLIs, authentication, RBAC, cloud control planes, or broad model/provider marketplaces in the current slice.

Recommended implementation order: harness adapter boundary first, durable event/state persistence second, and optional plugin hooks later.
