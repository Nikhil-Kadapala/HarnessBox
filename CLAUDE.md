# For AI Coding Agents

This file guides AI Coding Agents when working on the HarnessBox project.

## What is HarnessBox

HarnessBox is a platform for running AI coding agents in secure sandbox environments. It consists of:

- **`sdk/`** — Python SDK providing sandbox security, workspace, and harness primitives. Zero runtime dependencies — provider SDKs are optional extras.
- **`app/web/`** — Web application (planned)
- **`app/desktop/`** — Desktop application via Tauri (planned)

## Commands

### SDK (`sdk/`)

```bash
cd sdk
uv sync                          # Install all dependencies
uv run pytest tests/ -v          # Run all tests (~0.2s, uses MockProvider)
uv run pytest tests/test_sandbox.py -v                                    # Single file
uv run pytest tests/test_workspace.py::TestGitWorkspaceInject::test_clone_public_repo -v  # Single test
uv run ruff check .              # Lint
uv run ruff format --check .     # Format check
uv run mypy .                    # Type check (strict for source, relaxed for tests)
uv run ruff check . && uv run mypy . && uv run pytest tests/ -v  # Full CI check
```

### Web App (`app/web/`)

```bash
cd app/web
bun install                      # Install all dependencies
bun run dev                      # Dev server (Vite)
bun run build                    # Type check + production build
bun run test                     # Run vitest tests
bun run lint                     # Lint with oxlint
bunx tsc --noEmit                # Type check only
bunx vitest run                  # Run tests directly
```

CI runs lint → type check → tests on PRs targeting main.

# Important Rules

## Auto Compaction
Follow this when the context window is filled over 50%.
Carefully watch for meaningful conversation boundaries and tool call boundaries to identify checkpoints where it is most beneficial and safe to compact without losing critical information.
Do not wait until compaction gets auto-triggered midway through implementation.
Save context with `/context-save` so you can refer back after compaction with `/context-restore`.

## Intent before Implementation
Make sure to ask enough questions to clearly capture the user's intent before creating plans for new features, upgrades, or revamps. Probe the user to clearly state their intent and make outcomes explicit so implementation results in maximum success.

## Tool Invocation Priority
When executing tasks, follow this tool selection hierarchy:
1. **Read before write**: Always read existing files/code before modifying
2. **Search before create**: Search codebase for existing patterns before adding new ones
3. **Lint/type-check after every change**: Run `ruff check` + `mypy` in `sdk/` before declaring done
4. **Test before PR**: Run relevant `pytest` scope minimally before opening a PR

## Parallel Subagent Guidelines
Spawn parallel subagents when:
- Multiple independent test files need to be written for the same feature
- Code review + documentation update can proceed simultaneously
- Independent module changes have no shared file writes

Do NOT parallelize when:
- Tasks have sequential data dependencies (e.g., define protocol → then implement provider)
- One task's output is another's input
- Shared file writes would create merge conflicts

## When to Stop and Clarify (Mandatory)
ALWAYS pause and ask before proceeding if:
- The task involves changes to the **`SandboxProvider` protocol** or `Workspace` protocol
- The task touches **security policy** or credential guard definitions
- The task requires **new runtime dependencies** (SDK must stay zero-dep at runtime)
- The task changes the **server API contract** (`/v1/sessions/*` endpoints)
- You are unsure which module owns a given responsibility
- A feature spans 3+ modules without a clear seam

## Do Not List
- Never add runtime dependencies to the SDK — provider SDKs are optional extras only
- Never modify `SandboxProvider` protocol without user confirmation
- Never hardcode sandbox credentials or API keys
- Never use broad `git add` commands (`git add .`, `git add -A`) — always stage specific files
- Never include internal tracking references (Notion URLs, project links) in PR descriptions or commit messages

## Development Workflow
When working on fresh issues or tasks:
- Create a GitHub Issue first if appropriate before starting work
- For new features or major refactors, create a new branch. For small fixes, stay on the current working branch
- After implementation and testing (including CI), commit and create a PR
- Run the full CI check (`ruff check . && mypy . && pytest tests/ -v`) before declaring done

## CI & Merge Policy
- PR CI must pass before merge — no bypassing failed checks
- Always use **merge commits** (not squash or rebase) so the exact commits that passed CI land on `main` unchanged
- No force-merges past conflicts or failed checks

## Commit Message Format
Use conventional commits: `<type>(<scope>): <description>`
- Types: `feat`, `fix`, `refactor`, `test`, `chore`, `docs`
- Scope: use the module name (e.g., `feat(streaming): add event deduplication`)
- Body: include the linked GitHub issue number (`Closes #<issue_number>`) when applicable
- Never use generic messages like "fix bug" or "update code"
- Never add self-attributed author credits like `co-authored by claude code`

## Error Recovery Protocol
- **CI failure**: Analyze the failing step. Fix the root cause, never suppress linter errors with `# noqa` without a comment explaining why.
- **Type errors from mypy**: Fix the type, do not use `# type: ignore` unless the library lacks stubs (add a comment if so).
- **Failing pytest**: Never skip tests. If a test is genuinely obsolete, ask the user before deleting it.

## Task Completion Checklist
Before marking any task done, confirm:
- [ ] All new code has passing lint (`ruff check .`) and types (`mypy .`)
- [ ] New logic has at least one corresponding pytest
- [ ] Tests pass (`pytest tests/ -v`)
- [ ] PR description includes: what changed, why, and how to test it
- [ ] No secrets, debug prints, or leftover `TODO`s in committed code
- [ ] GitHub Issue is linked to the PR when applicable

## Architecture

### Core Flow

`HarnessBox` is the public SDK entry point. `Sandbox` is the internal orchestrator.

**Public API (for SDK users):**
1. **Construct** — `HarnessBox(provider="e2b", harness="claude-code", secrets=..., workspace_config=...)`
2. **Create Session** — `session = await hb.create_session(branch="feat/x")` provisions sandbox, injects config, clones workspace, runs setup
3. **Execute** — `async for event in session.send_message(prompt)` or `await session.run_command(cmd)`
4. **Snapshot** — `snapshot = await hb.save_snapshot()` / `HarnessBox.create_from_snapshot(id)`
5. **Kill** — `await hb.kill()` destroys all sessions

**Internal orchestration (Sandbox, used by WorkspaceManager and server):**
1. **Construct** — `Sandbox(client="e2b", harness="claude-code", security_policy=..., workspace=...)`
2. **Setup** — `await sandbox.setup()` creates the sandbox, builds a manifest of files/dirs/env vars, injects them, clones the git workspace, runs the setup script
3. **Execute** — `await sandbox.run_prompt(prompt)` streams agent output (text or typed events), or `await sandbox.start_interactive_session()` for PTY
4. **End** — `await sandbox.end()` commits/pushes workspace changes, destroys sandbox

### Module Responsibilities

All SDK source lives under `sdk/src/harnessbox/`.

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

### Key Design Decisions

- **Protocol-based extensibility** — `SandboxProvider` is a `Protocol` class (structural typing), not an ABC. All providers must implement the full git API (9 methods).
- **Single source of truth for guards** — Each `CredentialGuardSet` defines `bash_deny_globs`, `read_deny_globs`, and `hook_regexes` together.
- **Credentials never as env vars** — Git auth tokens use `git credential helper`, not environment variables.
- **Manifest is pure computation** — `build_manifest()` takes config and returns a `SandboxManifest`. No I/O.
- **Fail-open hook guard** — PreToolUse hooks exit 0 on errors, prioritizing availability over strict blocking.
- **Setup script runs after workspace inject** — Agent config files overlay on top of cloned repo contents.

### Extension Points

**Adding a provider**: Create `sdk/src/harnessbox/_providers/yourprovider.py` implementing `SandboxProvider` protocol, register in `_providers/__init__.py`, add optional dependency in `sdk/pyproject.toml`.

**Adding a harness type**: Call `register_harness_type(HarnessTypeConfig(...))` in `config/harness.py`.

## Testing

All tests use `MockProvider` from `sdk/tests/conftest.py` — an in-memory provider that tracks commands, files, and state. No real sandboxes are created. Tests are fast (~0.2s total).

## Conventions

- Python 3.12+, async throughout, stdlib only at runtime
- Ruff: line length 100, E501 ignored
- Mypy strict for `harnessbox/`, relaxed for `tests/`
- `uv` for dependency management (not pip)
- Conventional commits: `feat:`, `fix:`, `docs:`, `test:`

## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues (`Nikhil-Kadapala/HarnessBox`). See `docs/agents/issue-tracker.md`.

### Triage labels

Default label vocabulary (needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout — one `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
