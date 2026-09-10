# TODOs

Active follow-up work only. Completed, superseded, and removed-product ideas are
not tracked here.

## Project → Workspace follow-ups

These items were deferred by the 2026-09-10 engineering review of the
Project-defined Workspace model.

### Web Project → Workspace create flow

Add the dashboard flow for synchronous Project creation followed by Workspace
creation with `project_id` and `branch`. The web client currently posts the
legacy inline Git shape and drops `project_id`.

Touch points: `apps/web/src/lib/api.ts`,
`apps/web/src/hooks/use-session-manager.ts`, session/project creation UI, and
`apps/web/src/types.ts`.

Depends on the Project CRUD and Project-backed Workspace APIs. Ship before
considering dashboard dogfood green.

### Rename `ProjectConfig` to `RepoConfig`

Rename the `.harnessbox.toml` configuration types to `RepoConfig`,
`RepoConfigError`, and `load_repo_config` so “Project” refers only to the
server Project resource.

Touch points include `packages/sdk/src/harnessbox/config/project.py`, related
pipeline imports, and configuration tests. Make this a small dedicated change
after the Project APIs land.

### Conversation-level turn locking

Change `SessionRouter.prompt()` so turns serialize only within the same
`conversation_id`. Different Conversations in one Workspace must be able to
run concurrently against the shared checkout, with pause/idle behavior tested
under overlap.

Cross-Conversation file and Git conflicts remain caller-owned.

### Project mounts and uploads

Move filesystem mount and upload ownership to Project. Persist and validate
Project references, then materialize them when creating a Workspace. Keep the
Git-only Project slice small until Project → Workspace dogfood works.

## Harness architecture

These follow from the review of Omnigent, Omnara, and DeepSeek Harness.

### Harness adapter registry

Put Claude Code, Codex, and future harnesses behind a stable adapter boundary
for lifecycle, prompt delivery, resume, and `UniversalEvent` streaming. Keep
the existing sandbox provider protocol underneath it.

### Durable state and event persistence

Persist lifecycle state, turn boundaries, native agent session ids, and events
atomically so conversations can resume after crashes or sandbox replacement.

### Optional plugin hooks

Define a small optional extension point for harnesses, tools, storage, and
lifecycle hooks. Do not make the runtime depend on DeepSeek Harness or Cordis.

## Other active product gaps

### Model selection after slim Workspace creation

Restore model selection through a follow-up configure or create-session flow.
Do not put `model` back on the slim Workspace create request. Wire the web
`defaultModel` setting to the chosen follow-up API.

### Public terminal-state semantics

Review whether the public status model should distinguish clean completion,
crash/death, and shutdown instead of mapping all terminal runtime states to
`KILLED`. Add the change only if monitoring or client-facing dashboards need
that distinction.

### Additional sandbox providers

Before adding Daytona, Docker, or another real provider, decide whether the
native Git capability should remain mandatory or whether a provider adapter
should supply a shell-based fallback. Document the provider contract either
way.

### Per-user process isolation

Design paid-tier isolation only when multi-user hosted execution requires it.
The current OSS/server model does not promise per-user process isolation.
