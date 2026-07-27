---
type: Repo Doc
title: Safety & Development Rules
description: Stop-and-clarify triggers, do-not list, tool priority, and task completion checklist for agents.
tags: [security, sdk, agent, ci]
status: stable
generated: { by: process:okf-migration, at: 2026-07-27T19:33:00Z }
---

# Safety & Development Rules

Read this before modifying the codebase or declaring tasks complete. Prefer [`AGENTS.md`](../../AGENTS.md) when both overlap — this file is the on-demand deep dive.

## Auto Compaction

When the context window is over ~50% full, save with `/context-save` at a safe boundary and restore with `/context-restore` after compaction. Never overwrite root `CONTEXT.md` (domain glossary).

## Intent before Implementation

Ask enough questions to capture intent, success conditions, and constraints before planning new features or revamps.

## Tool Invocation Priority

1. **Read before write**
2. **Search before create**
3. **Lint/type-check after every SDK change** — `uv run ruff check .` + `uv run mypy .` in `packages/sdk/`
4. **Test before PR** — narrowest pytest scope first, then the full suite

## Parallel Subagent Guidelines

Spawn parallel subagents for independent SDK vs web work, independent tests, or read-only exploration across distinct directories.

Do **not** parallelize sequential protocol→implementation work, producer/consumer data dependencies, or shared-file edits that would conflict.

## When to Stop and Clarify (Mandatory)

ALWAYS pause and ask before proceeding if:

- The task changes the **`SandboxProvider`** protocol (`providers.py`) or the **`Workspace`** protocol (`workspace.py`)
- The task touches **security policy or credential guards** (`security/policy.py`, `guards.py`, `hooks.py`, `credentials.py`)
- The task requires a **new runtime dependency** (SDK runtime is stdlib-only; provider SDKs are optional extras)
- The task changes the **HTTP API contract** (`/v1/workspaces/*`, `/v1/harnesses`, `/v1/credentials/status`, and friends)
- The task needs a **new SQLite migration** (forward-only; never edit existing migrations)
- The task changes the **`UniversalEvent`** schema in `streaming.py`
- You are unsure which module owns a responsibility
- A feature spans **3+ modules across SDK and web** without a clear seam

## Do Not List

- Never add runtime dependencies to the SDK — provider SDKs stay optional extras (`harnessbox[e2b]`)
- Never modify `SandboxProvider` or `Workspace` protocols without user confirmation
- Never hardcode sandbox credentials, API keys, or tokens; never pass git auth tokens as environment variables
- Never weaken a credential guard or deny rule to make a test pass
- Never edit or delete an existing migration file; add a new one
- Never use broad staging (`git add .`, `git add -A`) — stage specific paths
- Never include internal tracking references (Notion URLs, project links) in PR descriptions or commit messages
- Never suppress `ruff`/`mypy` with bare `# noqa` / `# type: ignore` without justification

## Development Workflow

- Create a GitHub Issue first when appropriate
- New feature / major refactor → new branch or worktree; small fix → current branch
- Run the full local CI check before opening a PR
- After implementation and tests pass, commit and open a PR

## Task Completion Checklist

- [ ] GitHub Issue linked when applicable
- [ ] SDK lint + format + mypy clean
- [ ] New logic has at least one pytest in the right tier
- [ ] Full SDK suite passes
- [ ] Web build/tests if `apps/web/` changed
- [ ] Docs updated when behavior changed (this tree, `README.md`, `CHANGELOG.md`)
- [ ] PR describes what / why / how to test
- [ ] No secrets, debug prints, or leftover `TODO`s
