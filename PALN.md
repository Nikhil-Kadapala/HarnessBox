# Sandbox Refactor Plan

## Goal

Refactor the current `Sandbox` implementation (1021 lines) into three internal
collaborators while preserving the existing public API and behavior.

Target internal seams:

1. `SandboxSession` — VM lifecycle
2. `WorkspaceMount` — setup resolution + runtime git operations
3. `AgentRuntime` — agent process, streaming, cost tracking, PTY

## Reference Implementation

OpenComputer SDK uses the same structural pattern: `sandbox.exec`, `sandbox.files`,
`sandbox.pty`, `sandbox.agent` are sub-objects grouped by capability domain. Their
lifecycle methods (create/kill/hibernate/wake/checkpoint) stay on the Sandbox class
itself. We mirror this with internal visibility since our public API is `HarnessBox`,
not `Sandbox`.

## Scope

- Keep `Sandbox` as the internal facade (public API is HarnessBox).
- Move lifecycle concerns behind `SandboxSession`.
- Move setup/workspace/git mounting concerns behind `WorkspaceMount`.
- Move agent process and event streaming concerns behind `AgentRuntime`.
- Preserve backward compatibility: all 686 existing tests pass without modification.
- `EventBuffer` stays on `Sandbox` (shared channel), injected into both
  `AgentRuntime` and `SandboxSession`.

## Architecture

```
Sandbox (facade, ~200 lines after refactor)
  │ owns
  ├── EventBuffer (shared event channel)
  ├── SandboxSession (lifecycle)
  │     ├── provider state transitions
  │     ├── pause / resume / hibernate / wake
  │     ├── VM snapshots
  │     └── idle timer management
  ├── WorkspaceMount (setup + git)
  │     ├── resolve files/skills/plugins/prompt (setup-time)
  │     ├── build_setup_context()
  │     ├── cwd / plugin_dirs synchronization
  │     └── git facade: rename_branch, create_pr, diff, etc.
  └── AgentRuntime (agent execution)
        ├── one-shot streaming (_stream_oneshot)
        ├── persistent mode (_ensure_agent_ready, _stream_events)
        ├── send_message() overloads + _collect_response
        ├── AgentProcess lifecycle
        ├── interactive PTY (start_interactive_session)
        ├── session_id tracking
        └── cost metrics
```

## Planned Steps

1. Create `sdk/src/harnessbox/_internal/session.py` with `SandboxSession`.
2. Create `sdk/src/harnessbox/_internal/workspace_mount.py` with `WorkspaceMount`.
3. Create `sdk/src/harnessbox/_internal/runtime.py` with `AgentRuntime`.
4. Refactor `Sandbox` to compose these three collaborators.
5. All existing tests must pass unchanged (regression guard).
6. Add focused unit tests for each collaborator's construction.
7. Run full CI: `ruff check . && ruff format --check . && mypy . && pytest tests/ -v`

## Design Direction

### `SandboxSession`

File: `sdk/src/harnessbox/_internal/session.py`

Receives: `provider`, `event_handler`, `event_buffer`, `session_timeout`, `session_lock`

Own:
- RuntimeState tracking + `_transition()`
- `_emit_event()` for lifecycle events (SETUP_COMPLETE, SESSION_END)
- `_push_lifecycle_event()` for stream events (SESSION_STARTED, SESSION_ENDED)
- pause / resume / hibernate / wake
- create_snapshot / create_vm_snapshot
- idle timer (start / cancel / _on_idle_timeout / _do_idle_pause)
- kill / end

### `WorkspaceMount`

File: `sdk/src/harnessbox/_internal/workspace_mount.py`

Receives: `harness_config`, `workspace`, `provider` (after setup)

Own:
- Static resolvers: _resolve_files, _resolve_prompt, _resolve_skills, _resolve_plugins
- build_setup_context() construction
- Post-setup cwd/plugin_dirs sync
- Git facade: rename_branch, create_pr, check_pr_status, diff, diff_stat,
  commit_count, create_workspace_checkpoint, restore_workspace_checkpoint

### `AgentRuntime`

File: `sdk/src/harnessbox/_internal/runtime.py`

Receives: `provider`, `harness_config`, `event_buffer`, `cwd`, `skip_permissions`,
           `model`, `one_shot`, `plugin_dirs`, `timeout`

Own:
- `_stream_oneshot()` — one-shot agent invocation
- `_ensure_agent_ready()` — persistent process management
- `send_message()` overloads (stream=True/False)
- `_stream_events()` — core streaming loop + SandboxDeadError handling
- `_collect_response()` — non-streaming accumulator
- `start_interactive_session()` — PTY
- `agent_session_id` tracking
- `cost_metrics` property + `_snapshot_process_metrics()`
- AgentProcess instance management

### Cross-Cutting: SandboxDeadError

When `AgentRuntime._stream_events()` catches `SandboxDeadError`:
1. It emits the error event to `event_buffer` (injected)
2. It calls a `on_sandbox_dead` callback (set by Sandbox) which transitions
   SandboxSession state to DEAD

This avoids AgentRuntime importing or knowing about SandboxSession.

## NOT in Scope

- Public API changes (HarnessBox, Session remain unchanged)
- server.py changes (still references `sandbox_conn` attributes)
- workspace_manager.py changes (creates Sandbox as before)
- New functionality (no new features, purely structural)

## What Already Exists

- `AgentProcess` (`process.py`) — already extracted, handles stdin/stdout/streaming
- `SetupPipeline` (`config/pipeline.py`) — already extracted, handles setup orchestration
- `GitRepoConfig` (`workspace.py`) — already extracted, handles git clone/push/PR
- `EventBuffer` (`events.py`) — already extracted, handles ring buffer + broadcast
- `CostMetrics` (`cost.py`) — already extracted, handles cost aggregation

These are the building blocks the collaborators will compose.

## Guardrails

- Do not break the current `Sandbox` API in this pass.
- Prefer internal composition over a large public API redesign.
- Keep VM lifecycle vocabulary (hibernate/wake/snapshot) distinct from workspace
  checkpoint vocabulary (create_workspace_checkpoint/restore_workspace_checkpoint).
- Preserve existing tests unless behavior is intentionally improved and covered.
- `_internal/` package signals "not for import by users" without a public API change.

## Implementation Tasks

- [ ] **T1 (P1, human: ~1h / CC: ~10min)** — _internal/session.py — Extract SandboxSession
  - Surfaced by: Architecture review — lifecycle is 130 lines + 50 lines idle timer
  - Files: `sdk/src/harnessbox/_internal/session.py`, `sdk/src/harnessbox/sandbox.py`
  - Verify: `pytest tests/test_sandbox.py tests/test_idle_pause.py -v`

- [ ] **T2 (P1, human: ~1h / CC: ~10min)** — _internal/workspace_mount.py — Extract WorkspaceMount
  - Surfaced by: Architecture review — resolvers + git facade = ~140 lines
  - Files: `sdk/src/harnessbox/_internal/workspace_mount.py`, `sdk/src/harnessbox/sandbox.py`
  - Verify: `pytest tests/test_sandbox_workspace.py tests/test_sandbox_files.py tests/test_setup.py -v`

- [ ] **T3 (P1, human: ~2h / CC: ~15min)** — _internal/runtime.py — Extract AgentRuntime
  - Surfaced by: Architecture review — agent execution = ~230 lines, most complex block
  - Files: `sdk/src/harnessbox/_internal/runtime.py`, `sdk/src/harnessbox/sandbox.py`
  - Verify: `pytest tests/test_sandbox_streaming.py tests/test_process.py tests/test_cost_tracking.py -v`

- [ ] **T4 (P2, human: ~30min / CC: ~5min)** — sandbox.py — Wire delegation + verify
  - Surfaced by: Architecture review — Sandbox becomes thin facade
  - Files: `sdk/src/harnessbox/sandbox.py`
  - Verify: `pytest tests/ -v` (full suite, all 686 tests)

## Worktree Parallelization

Sequential implementation, no parallelization opportunity. Each task depends on the
previous (T2 and T3 both depend on T1's SandboxSession for the state callback, T4
depends on all three).

## Failure Modes

| Codepath | Failure scenario | Test coverage | Error handling | User visible? |
|----------|-----------------|---------------|----------------|---------------|
| AgentRuntime._stream_events | SandboxDeadError mid-stream | Yes (test_sandbox.py) | Emits error event, transitions DEAD | Yes (SSE error event) |
| SandboxSession._do_idle_pause | Lock contention during pause | Yes (test_idle_pause.py) | Acquires session_lock | No (background) |
| WorkspaceMount.create_pr | Push fails | Yes (test_workspace.py) | Raises RuntimeError | Yes (HTTP 500) |

No critical gaps (all failures have tests + error handling + clear user feedback).

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | -- | -- |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | -- | -- |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR | 1 issue (EventBuffer ownership), 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | -- | -- |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | -- | -- |

- **UNRESOLVED:** 0
- **VERDICT:** ENG CLEARED -- ready to implement
