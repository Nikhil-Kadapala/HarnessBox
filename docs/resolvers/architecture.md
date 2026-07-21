# Resolver: Architecture & Module Map

This resolver contains the architectural design of HarnessBox, including its public/internal orchestration flows, module responsibility mapping, design invariants, and extension points. Read this file when analyzing codebase structure, adding providers/harnesses, or refactoring components.

## Core Flow

`HarnessBox` is the public SDK entry point. `Sandbox` is the internal orchestrator. Lifecycle status is a single `RuntimeState` enum everywhere (SDK + HTTP).

**Public API (for SDK users):**
1. **Construct** — `HarnessBox(provider="e2b", harness="claude-code", secrets=..., workspace_config=...)`
2. **Create Session** — `session = await hb.create_session(branch="feat/x")` provisions sandbox, clones workspace when configured, runs setup
3. **Execute** — `async for event in session.send_message(prompt)` or `await session.run_command(cmd)`
4. **Snapshot** — `snapshot = await hb.save_snapshot()` / `HarnessBox.create_from_snapshot(id)`
5. **Kill** — `await hb.kill()` destroys all sessions

**Internal orchestration (Sandbox, used by WorkspaceManager and server):**
1. **Construct** — `Sandbox(client="e2b", harness="claude-code", security_policy=..., workspace=...)`
2. **Setup** — `await sandbox.setup()` via `initialize_sandbox()`: create VM, check tools, workspace root, env, optional git/mount, optional setup script (no harness file injection)
3. **Execute** — `await sandbox.run_prompt(prompt)` streams agent output (text or typed events), or `await sandbox.start_interactive_session()` for PTY
4. **End** — `await sandbox.end()` commits/pushes workspace changes, destroys sandbox

## Module Responsibilities

All SDK source lives under `packages/sdk/src/harnessbox/`.

| Module | Role |
|--------|------|
| `harnessbox.py` | Public API — `HarnessBox` entry point, `Session` handle, `Snapshot`, `HarnessBoxSecrets`, `WorkspaceConfig` |
| `sandbox.py` | Internal orchestration — lifecycle, provider delegation, file I/O, agent execution |
| `streaming.py` | `UniversalEvent` schema + `StreamParser` — stateful NDJSON parser for Claude Code's `--output-format stream-json`, maps to UI events (text, thinking, tool calls, results) |
| `events.py` | `EventBuffer` — per-session ring buffer (1024) with async broadcast for SSE replay on reconnection |
| `session.py` | `SessionManager` + `SessionConfig` — multi-session registry with per-session locking |
| `server.py` | HTTP/SSE transport — Starlette endpoints at `/v1/sessions/*` for session CRUD + event streaming |
| `providers.py` | `SandboxProvider` protocol — the contract all providers implement |
| `_providers/e2b.py` | E2B implementation — wraps AsyncSandbox, adds native git API + PTY support |
| `_providers/__init__.py` | Provider registry — resolves string names ("e2b") to provider classes |
| `config/harness.py` | `HarnessTypeConfig` registry — defines how each agent type is invoked (CLI flags, config dirs, settings builders) |
| `config/manifest.py` | `build_manifest()` — pure function that computes all files/dirs/env vars to inject |
| `security/policy.py` | `SecurityPolicy` — denied tools, bash patterns, network blocking, credential guards; generates `settings.json` deny rules |
| `security/guards.py` | 10 composable `CredentialGuardSet`s — single source of truth for both settings.json and hook scripts |
| `security/hooks.py` | Generates PreToolUse hook scripts from guard regex patterns |
| `security/events.py` | Sandbox lifecycle events — `SandboxEvent` emission, `EventHandler` protocol |
| `lifecycle.py` | `RuntimeState` enum + valid transition map (STARTING→ACTIVE→DYING→ENDED/DEAD) |
| `workspace.py` | `GitRepoConfig` — clone, commit+push, diff; uses native E2B git API (provider protocol methods) |

## Key Design Decisions

- **Protocol-based extensibility** — `SandboxProvider` is a `Protocol` class (structural typing), not an ABC. All providers must implement the full git API (9 methods).
- **Single source of truth for guards** — Each `CredentialGuardSet` defines `bash_deny_globs`, `read_deny_globs`, and `hook_regexes` together.
- **Credentials never as env vars** — Git auth tokens use `git credential helper`, not environment variables.
- **Manifest is pure computation** — `build_manifest()` takes config and returns a `SandboxManifest`. No I/O.
- **Fail-open hook guard** — PreToolUse hooks exit 0 on errors, prioritizing availability over strict blocking.
- **Setup script runs after content inject** — Optional user setup_script runs after git clone / mount. Harness/agent files are not written during create (configure is a follow-up).

## Extension Points

**Adding a provider**: Create `packages/sdk/src/harnessbox/_providers/yourprovider.py` implementing `SandboxProvider` protocol, register in `_providers/__init__.py`, add optional dependency in `packages/sdk/pyproject.toml`.

**Adding a harness type**: Call `register_harness_type(HarnessTypeConfig(...))` in `config/harness.py`.
