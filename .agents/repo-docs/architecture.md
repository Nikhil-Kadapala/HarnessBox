---
type: Repo Doc
title: Architecture & Module Map
description: Core SDK/server flows, design invariants, extension points, and where to find the full module index.
resource: https://github.com/Nikhil-Kadapala/HarnessBox/blob/main/packages/sdk/src/harnessbox/harnessbox.py
tags: [sdk, server, architecture, lifecycle, http]
status: stable
generated: { by: process:okf-migration, at: 2026-07-27T19:33:00Z }
---

# Architecture & Module Map

Read this when analyzing codebase structure, adding providers or harnesses, or refactoring components. For the exhaustive per-file index, prefer [`AGENTS.md`](../../AGENTS.md) — this doc focuses on flows, invariants, and extension points.

## Core Flow

`HarnessBox` is the public SDK entry point. `Sandbox` is the internal orchestrator. Lifecycle status is a single `RuntimeState` enum everywhere (SDK + HTTP), including `PAUSED` and `ERROR`.

**Public API (SDK users):**
1. **Construct** — `HarnessBox(provider="e2b", harness="claude-code", secrets=..., workspace_config=...)`
2. **Create Session** — `session = await hb.create_session(branch="feat/x")` provisions a sandbox, clones the workspace when configured, runs setup
3. **Execute** — `async for event in session.send_message(prompt)` or `await session.run_command(cmd)`
4. **Snapshot** — `snapshot = await hb.save_snapshot()` / `HarnessBox.create_from_snapshot(id)`
5. **Kill** — `await hb.kill()` destroys all sessions

**Internal orchestration (`Sandbox`, used by `WorkspaceManager` and the server):**
1. **Construct** — `Sandbox(client="e2b", harness="claude-code", security_policy=..., workspace=...)`
2. **Setup** — `await sandbox.setup()` via `initialize_sandbox()`: create VM, check tools, workspace root, env, optional `setup_git` / `mount_fs`, optional setup script (no harness file injection on create)
3. **Execute** — `await sandbox.send_message(prompt)` streams agent output, or `await sandbox.start_interactive_session()` for PTY
4. **End** — teardown commits/pushes when configured and destroys the sandbox

**HTTP control plane:** FastAPI (`create_app()` in `server.py`) serves `/v1/workspaces/*`. Workspace IDs are the session identity on the wire — there is no `/v1/sessions/*` tree. See [`AGENTS.md`](../../AGENTS.md) for the full route table.

## Module Map (summary)

All SDK source lives under `packages/sdk/src/harnessbox/`.

| Area | Key modules | Role |
|------|-------------|------|
| Public surface | `harnessbox.py`, `client.py`, `providers.py`, `workspace.py`, `streaming.py`, `lifecycle.py`, `credentials.py` | User-facing types and protocols |
| Orchestration | `sandbox.py`, `process.py`, `events.py`, `_internal/*` | Sandbox lifecycle, agent process, event buffer |
| Providers | `_providers/e2b.py`, `_providers/__init__.py` | `SandboxProvider` implementations |
| Config | `config/harness.py`, `manifest.py`, `pipeline.py`, `project.py` | Harness registry, pure manifest, init pipeline |
| Security | `security/policy.py`, `guards.py`, `hooks.py`, `events.py` | Deny rules, credential guards, PreToolUse hooks |
| Server | `_server/*`, `cli.py`, `hbox/*` | HTTP/SSE, storage, idle, REPL |

## Key Design Decisions

- **Protocol-based extensibility** — `SandboxProvider` and `Workspace` are `Protocol` classes (structural typing), not ABCs.
- **Single source of truth for guards** — Each `CredentialGuardSet` defines deny globs and hook regexes together.
- **Credentials never as env vars** — Git auth tokens use a git credential helper, not environment variables.
- **Manifest is pure computation** — `build_manifest()` returns a `SandboxManifest` with no I/O.
- **Fail-open hook guard** — PreToolUse hooks exit 0 on errors, prioritizing availability.
- **Server-minted workspace identity** — HTTP create always mints `workspace_id`; client-supplied IDs are ignored. `project_id` stays null until a Project API exists.
- **Git cwd wins** — When git is configured, agent cwd is `/workspace/<clone_dir_name>` regardless of request `cwd`.
- **Event storage round-trip** — `UniversalEvent.to_storage_dict()` / `from_storage_dict()` keep full fidelity for `/history` and `events.jsonl`.

## Extension Points

**Adding a provider:** Implement `SandboxProvider` under `_providers/`, register in `_providers/__init__.py`, add an optional extra in `packages/sdk/pyproject.toml`.

**Adding a harness type:** Call `register_harness_type(HarnessTypeConfig(...))` in `config/harness.py`.

## Related

- [commands.md](commands.md) — local build/test commands
- [rules.md](rules.md) — stop-and-clarify triggers and do-not list
- [conventions.md](conventions.md) — style, commits, CI
- User-facing subsystem docs — [`docs/sandboxes/`](../../docs/sandboxes/)
