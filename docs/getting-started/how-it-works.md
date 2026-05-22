# How It Works

Your code talks to the **HarnessBox SDK**, which provisions a sandbox via a provider (E2B), injects agent configuration and security policies, clones your git workspace, and starts the AI agent. Prompts and agent output stream over the provider's transport layer.

```
┌─────────────┐      ┌──────────────┐      ┌─────────────────────────┐
│  Your Code  │─────▶│  HarnessBox  │─────▶│   Sandbox (E2B VM)      │
│             │      │     SDK      │      │  ┌───────────────────┐  │
│             │◀─────│              │◀─────│  │  AI Agent (Claude)│  │
│  (prompts)  │      │  (provider)  │      │  │  + Security Policy│  │
│  (events)   │      │              │      │  │  + Git Workspace  │  │
└─────────────┘      └──────────────┘      │  └───────────────────┘  │
                                           └─────────────────────────┘
```

## Lifecycle

Sessions have three user-facing states:

| Status | Description |
|--------|-------------|
| `running` | Active, accepting prompts and commands |
| `sleeping` | Paused to save cost, wakes transparently on next interaction |
| `killed` | User explicitly destroyed it, gone forever |

The lifecycle from the user's perspective:

1. **Create** — `hb.create_session()` provisions a sandbox, injects config, clones the workspace, starts the agent. Session is now `running`.
2. **Execute** — Send prompts and stream events, or run shell commands. If idle too long, the session `sleep`s automatically.
3. **Wake** — On the next interaction after sleeping, the sandbox resumes transparently. No manual action needed.
4. **Kill** — `session.kill()` commits workspace changes (if configured) and destroys the sandbox permanently.

## Providers

A provider is a backend that creates and manages VMs. HarnessBox uses a `SandboxProvider` protocol — any backend implementing it works.

| Provider | Status | Description |
|----------|--------|-------------|
| E2B | Stable | Cloud VMs with native git API, PTY support, fast boot |
| Mock | Testing | In-memory provider for unit tests (no real VMs) |

The provider handles: creating/destroying sandboxes, running commands, reading/writing files, and managing git operations.

## Harness Types

A harness defines which AI agent runs inside the sandbox and how it's configured.

| Harness | Agent | Description |
|---------|-------|-------------|
| `claude-code` | Claude Code CLI | Anthropic's coding agent with stream-json output |
| `codex` | OpenAI Codex CLI | OpenAI's coding agent |

Each harness type specifies: the CLI command, output format, config directory, and how to build settings files (permissions, security policies).

## Security Policies

A `SecurityPolicy` controls what the agent can do inside the sandbox:

- **Denied tools** — Block specific agent tools (e.g., prevent file writes to certain paths)
- **Bash deny patterns** — Block shell commands matching glob patterns
- **Network blocking** — Restrict outbound network access
- **Credential guards** — Prevent the agent from accessing or exfiltrating secrets

Security policies are injected as the agent's `settings.json` deny rules and as PreToolUse hook scripts that intercept tool calls at runtime.

## Git Workspaces

A `GitRepoConfig` defines a repository to clone into the sandbox:

- **Clone** — Repo is cloned after sandbox creation, using native git API when available
- **Branch** — Checkout a specific branch or create a new one
- **Credentials** — Git auth tokens use `git credential helper`, never environment variables
- **Commit & Push** — On teardown, changes can be committed and pushed automatically
- **Checkpoints** — Named snapshots of the workspace state (tag-based)

## Streaming

Agent output is parsed from NDJSON (Claude Code's `--output-format stream-json`) into typed `UniversalEvent` objects:

| Event Type | Description |
|------------|-------------|
| `USER_PROMPT` | Prompt sent to the agent |
| `AGENT_TEXT` | Text output from the agent |
| `THINKING` | Agent's internal reasoning |
| `TOOL_CALL` | Agent invoking a tool (Bash, Read, Write, etc.) |
| `TOOL_RESULT` | Result returned from a tool |
| `TURN_ENDED` | Agent finished responding |
| `SESSION_ENDED` | Session terminated |
| `ERROR` | Error occurred |

## Sessions

HarnessBox supports multiple concurrent sessions, each with its own sandbox, workspace, and agent instance. Sessions are managed by the `WorkspaceManager` which handles pooling, lifecycle transitions, and storage.

## Next Steps

- [Sandboxes Overview](../sandboxes/overview.md) — Full API reference for sandboxes
- [Security Policies](../sandboxes/security.md) — Detailed security configuration
- [Streaming Events](../sandboxes/streaming.md) — Event types and parsing
