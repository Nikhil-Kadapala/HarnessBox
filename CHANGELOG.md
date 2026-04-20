# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
- `HarnessTypeConfig` registry with built-in types: claude-code, codex, gemini-cli, opencode
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

[0.2.0]: https://github.com/Nikhil-Kadapala/HarnessBox/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/Nikhil-Kadapala/HarnessBox/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/Nikhil-Kadapala/HarnessBox/releases/tag/v0.1.0
