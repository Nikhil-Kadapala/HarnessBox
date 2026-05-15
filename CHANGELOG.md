# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0.0] - 2026-05-14

### Added
- **Streaming architecture** with full event coverage: `UniversalEvent` schema, `StreamParser` for Claude Code's NDJSON output, typed `CONTEXT_UPDATE`, `COST_UPDATE`, and `USER_PROMPT` events
- **WorkspaceManager** replacing SessionManager: multi-workspace registry with per-session locking, branch-based pooling, auto-pause with snapshot creation
- **SQLite storage backend** as default persistence layer: batched event writes, migration runner, 10K event retention cap per workspace, WAL mode
- **Migration system** with versioned SQL migrations (`v001_initial`, `v002_event_type_index`)
- **CLI entrypoint** (`harnessbox serve`) with env vars + flags for port, db path
- **HTTP/SSE server** with FastAPI: workspace CRUD, prompt submission with SSE streaming, event history replay, permission handling
- **USER_PROMPT events** with attachment support (inline base64 for <1MB, filesystem path for larger files)
- **Cost tracking** with per-model breakdown, `CostMetrics` dataclass, persistent cost history via events table query
- **AgentManager** for lazy process spawning and multi-conversation agent lifecycle
- **Credential injection** system: Claude auth env vars (Bedrock/Vertex/direct), gcloud ADC file injection, GitHub token resolution
- **Security guards** (10 composable `CredentialGuardSet`s) generating both settings.json deny rules and PreToolUse hook scripts
- **Web application** (app/web): React + Vite with session board, event feed, settings panel, dot-matrix loading animations, real-time SSE consumption
- **Monorepo structure** with `sdk/`, `app/web/`, `app/desktop/` layout

### Changed
- **BREAKING:** Renamed `start_persistent` to `start_session`, added `one_shot` flag
- **BREAKING:** Renamed API method to `send_message` (was `run_prompt`)
- **BREAKING:** `SandboxProvider` protocol now includes `start_session` (previously delegated)
- `AgentResponse` moved to `types.py` module, E2B exceptions encapsulated behind `SandboxDeadError`
- Server defaults to SQLite storage (was in-memory only)
- Event buffer now uses asyncio.Lock covering flush task (fixes race condition on `_pending_events`)

### Removed
- Old flat package structure at repo root (`harnessbox/` directory replaced by `sdk/src/harnessbox/`)
- Stub providers (Docker, Daytona, EC2) removed from source tree
- `SupabaseBackend` and `AuthProvider` concepts (multi-tenancy handled by auth gateway at infra level)
- `preferences` table (YAGNI)
- Separate `cost_history` table (cost queries go through events table)

## [0.2.0] - 2026-04-20

### Added
- `SandboxEvent` frozen dataclass for structured session event logging
- `EventType` enum: `SETUP_COMPLETE`, `SESSION_END`, `COMMAND_RUN`, `STATE_CHANGED`
- `EventHandler` async protocol for receiving sandbox events
- `JsonLogger` built-in handler (prints JSON lines to stdout)
- `CallbackHandler` built-in handler (calls user-provided sync or async callable)
- `event_handler` parameter on `Sandbox` constructor
- `examples/quickstart.py` runnable demo script

### Changed
- **BREAKING:** Module restructure into subpackages:
  - `harnessbox.harness` → `harnessbox.config.harness`
  - `harnessbox._setup` → `harnessbox.config.manifest`
  - `harnessbox.security` → `harnessbox.security.policy`
  - `harnessbox.hooks` → `harnessbox.security.hooks`
  - All symbols remain importable from `harnessbox` (top-level) for convenience
- Improved error messages: state transition errors now include actionable hints
- README install instructions fixed (was showing "from source", now shows `pip install`)

### Removed
- Old flat module files (`harness.py`, `_setup.py`, `security.py`, `hooks.py` at package root)

## [0.1.1] - 2026-04-19

### Fixed
- Added README rendering on PyPI (was missing `readme` field in pyproject.toml)
- Added project URLs, classifiers, and keywords to PyPI metadata

## [0.1.0] - 2026-04-19

### Added
- `Sandbox` class with multi-provider support (E2B, Docker, Daytona, EC2)
- `SandboxProvider` protocol for custom provider implementations
- `HarnessTypeConfig` registry with built-in types: claude-code, codex, opencode
- `SecurityPolicy` with credential deny rules and PreToolUse hook guard
- `GitWorkspace` for cloning repos into sandboxes with optional commit+push on exit
- `Workspace` protocol for extensibility
- `MountWorkspace` stub (not yet implemented)
- `SessionState` lifecycle machine with validated transitions
- `setup_script` parameter for pre-agent environment setup
- Auth via git credential helper (no env var exposure)
- Workspace events: on_clone_start, on_clone_complete, on_commit, on_push_success, on_push_failure
- Workspace snapshots (checkpoint/restore via git tags)
- Workspace diff (unified diff since clone or last snapshot)
- Git credential deny rules (.git/config, .git-credentials, git config credential.*)
- 214 tests

[0.3.0.0]: https://github.com/Nikhil-Kadapala/HarnessBox/compare/v0.2.0...v0.3.0.0
[0.2.0]: https://github.com/Nikhil-Kadapala/HarnessBox/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/Nikhil-Kadapala/HarnessBox/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/Nikhil-Kadapala/HarnessBox/releases/tag/v0.1.0
