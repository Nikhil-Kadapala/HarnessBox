# For AI Coding Agents

This file is the single source of truth for AI Coding Agents working on the HarnessBox project. `CLAUDE.md` imports it (`@AGENTS.md`), so Claude Code, Codex, and OpenCode all read the same instructions. Edit this file, not `CLAUDE.md`.

## Agent Role Clarification

You are operating as a principal engineering agent on the HarnessBox monorepo. You have access to the Python SDK (`packages/sdk/`), the React dashboard (`apps/web/`), and the cloud API (`apps/api/`). You do NOT have direct production access — all changes go through the PR + review gate. Treat `main` as the base branch for every PR unless instructed otherwise; never push directly to `main`.

HarnessBox runs untrusted AI agents inside sandboxes, so security posture is a product feature, not an implementation detail. When a change touches `security/`, `credentials.py`, or provider auth, assume it is high-risk and slow down.

# Important rules to always follow

## Auto Compaction (very important)

Follow this when the context window is filled over 50%.
Carefully watch for meaningful conversation boundaries and tool call boundaries within conversations to identify checkpoints where it is most beneficial and safe to compact the conversation without losing any critical information and preserving the intent.
Do not wait until compaction gets auto-triggered midway through implementation and risk losing critical information.
Save the context with `/context-save` so you can restore it after compaction with `/context-restore` and be sure you still have the full picture. Never overwrite the root `CONTEXT.md` — that file is the project's domain glossary, not scratch space.

## Intent before Implementation

HarnessBox exists to make autonomous agent execution safe and legible. That same standard applies to how you work: ask enough questions to clearly capture the user's intent before you write a plan for any new feature, upgrade, or revamp. Probe the user to state their intent explicitly, and make the success conditions and constraints explicit in the plan, so the implementation results in maximum success and satisfaction rather than a plausible-looking guess.

## Development workflow

Do this when working on fresh issues or tasks:

- Always create a GitHub Issue first if appropriate before starting work. If an issue is not warranted under standard development and CI/CD practice for the task, you can skip it. See [issue-tracker.md](.agents/repo-docs/issue-tracker.md) for the `gh` CLI conventions and [triage-labels.md](.agents/repo-docs/triage-labels.md) for label vocabulary.
- Read the relevant repo-docs (see [Deep-Dive Docs](#deep-dive-docs-read-on-demand)) before planning changes to an area you have not touched in this session.
- Use the vocabulary defined in `CONTEXT.md` (Sandbox, Workspace, Session, HarnessBox) in issue titles, branch names, tests, and code. Do not drift to synonyms.
- For a new feature or major refactor, create a new branch or a git worktree and work there. For a small fix or cleanup, stay on the current working branch.
- Run the full local CI check before opening a PR: `cd packages/sdk && uv run ruff check . && uv run mypy . && uv run pytest tests/ -v`.
- After implementation and testing pass, commit and open a PR.

## Tool Invocation Priority

When executing tasks, follow this tool selection hierarchy:

1. **Read before write**: Always read existing files/code before modifying.
2. **Search before create**: Search the codebase for existing patterns before adding new ones — especially before adding a helper, an event type, or a config field.
3. **Lint/type-check after every SDK change**: Run `uv run ruff check .` + `uv run mypy .` in `packages/sdk/` before declaring done.
4. **Test before PR**: Run the narrowest relevant `pytest` scope first, then the full suite (it is ~seconds, there is no excuse to skip it).

## Parallel Subagent Guidelines

Spawn parallel subagents when:

- SDK module changes and `apps/web/` component changes are independent and non-conflicting.
- Multiple independent test files need to be written for the same feature.
- Code review and documentation updates can proceed simultaneously.
- Read-only codebase exploration can be split across distinct directories.

Do NOT parallelize when:

- Tasks have sequential data dependencies (e.g., change the `SandboxProvider` protocol → then implement it in E2B).
- One task's output is another's input.
- Shared file writes would create merge conflicts (two agents editing `streaming.py` or `sessions.py` will collide).

## When to Stop and Clarify (Mandatory)

ALWAYS pause and ask before proceeding if:

- The task involves changes to the **`SandboxProvider` protocol** (`providers.py`) or the **`Workspace` protocol** (`workspace.py`) — every provider must implement the full surface.
- The task touches **security policy or credential guards** (`security/policy.py`, `security/guards.py`, `security/hooks.py`, `credentials.py`).
- The task requires a **new runtime dependency** — the SDK's runtime is stdlib-only, and provider SDKs are optional extras.
- The task changes the **HTTP API contract** (`/v1/workspaces/*`, `/v1/harnesses`, `/v1/credentials/status`, and friends) that `apps/web` and `HarnessBoxClient` both depend on.
- The task needs a **new SQLite migration** (`_server/_storage/migrations/`) — schema changes are forward-only and land in release order.
- The task changes the **`UniversalEvent` schema** in `streaming.py`, which the web event feed parses.
- You are unsure which module owns a given responsibility.
- A feature spans **3+ modules across SDK and web** without a clear seam.

## Do Not list

- Never add runtime dependencies to the SDK — provider SDKs stay optional extras (`harnessbox[e2b]`).
- Never modify the `SandboxProvider` or `Workspace` protocol without user confirmation.
- Never hardcode sandbox credentials, API keys, or tokens; never pass git auth tokens as environment variables (use the git credential helper).
- Never weaken a credential guard or deny rule to make a test pass — fix the test.
- Never edit or delete an existing migration file in `_server/_storage/migrations/`; add a new one.
- Never use broad staging commands (`git add .`, `git add -A`) — always stage specific files.
- Never include internal tracking references (Notion URLs, project links) in PR descriptions, commit messages, or any public-facing content.
- Never suppress `ruff`/`mypy` findings with bare `# noqa` or `# type: ignore` — see the Error Recovery Protocol.

## CI & Merge Policy

- PR CI must pass before merge is allowed — no bypassing failed checks.
- Always use **merge commits** (not squash or rebase) so the exact commits that passed CI land on `main` unchanged.
- No force-merges past conflicts or failed checks.
- `.github/workflows/ci.yml` runs on push and PR to `main`, scoped to `packages/sdk`:
  - `sdk-lint-format-type-check` — `uv sync`, `ruff check`, `ruff format --check`, `mypy`, `bandit`, `pip-audit`.
  - `sdk-tests` — matrix on Python 3.12 and 3.13, `pytest tests/` with a coverage floor (~64%), Codecov upload on 3.12 only.
- CI does **not** currently build or test `apps/web` or `apps/api`. Run `bun run build` and `bun run test` locally before opening a PR that touches the web app.
- E2E tests are collected but skipped without `E2B_API_KEY`, so green CI does not prove real-sandbox behavior. Say so explicitly when a change affects provider integration.
- `.github/workflows/publish.yml` publishes `packages/sdk` to PyPI via OIDC when a GitHub release is published.

## Skill Routing — Passive Context for Precise Invocation

IMPORTANT: Prefer skill-led and retrieval-led reasoning over pre-training for any technology or workflow below. When a task matches a trigger, invoke the skill BEFORE generating code or advice.

### Documentation & Reference
`/find-docs-with-ctx7`: external tech docs, API refs, SDK params, CLI flags, framework and migration guides | NOT: internal project code or architecture questions (read `.agents/repo-docs/`)

### Sandboxes & Infrastructure
`/e2b`: E2B cloud sandboxes — sandbox lifecycle, templates, code-interpreter, desktop sandboxes, E2B CLI | NOT: our own `SandboxProvider` protocol (read `_providers/e2b.py` and `providers.py`)
`/gcloud-cli`: GCP services — Cloud Run, IAM, Secret Manager, Artifact Registry, GKE, Logging, Monitoring | NOT: AWS, Azure, Terraform-only tasks
`/cli-for-agents`: designing or reviewing CLIs that agents drive — non-interactive flags, layered `--help`, stdin, actionable errors | Invoke when changing `harnessbox serve` or the `hbox` REPL

### Cloud API Dependencies (`apps/api/`)
`/supabase`: Supabase Auth, Database, Edge Functions, `supabase-js`, session/JWT handling | Invoke for `auth.py` / `auth_routes.py` work
`/supabase-postgres-best-practices`: Postgres queries, schema design, indexes, RLS, performance tuning | NOT: our SQLite storage backend
Stripe has no installed skill — use `/find-docs-with-ctx7` for `billing.py` / `billing_routes.py` work.

### Frontend (`apps/web/`)
`/vercel-react-best-practices`: React performance — re-renders, memoization, data fetching, bundle size | Invoke before refactoring components or hooks
`/web-design-guidelines`: UI code review for accessibility and interface guidelines | "review my UI", "check accessibility"
`/frontend-design`: aesthetic direction, typography, visual intent for new UI

### Ideation & Planning (gstack)
`/office-hours`: brainstorm and ideate — "I have an idea", "is this worth building" | Run before `/plan-ceo-review`
`/spec`: turn vague intent into a precise executable spec in five phases
`/plan-ceo-review`: rethink scope — "think bigger", "expand scope", "strategy review"
`/plan-eng-review`: architecture review — "lock in the plan", edge cases, data flow, test coverage
`/plan-design-review`: design plan critique, rates dimensions 0–10 | Before implementing UI/UX
`/plan-devex-review`: developer experience review of a plan | Invoke for SDK/CLI surface changes
`/autoplan`: runs CEO, design, eng, and DX reviews sequentially with auto-decisions | "run all reviews"

### Design (gstack)
`/design-consultation`: create a design system + DESIGN.md — typography, color, layout, motion
`/design-shotgun`: generate multiple design variants for comparison
`/design-review`: visual QA on a live site — spacing, hierarchy, AI-slop detection, then auto-fixes
`/design-html`: production-quality HTML/CSS finalization

### Browser, QA & Performance (gstack)
`/browse`: open a URL, screenshot, interact, verify state, diff before/after | Use for all web browsing
`/qa`: systematic QA + fix loop — "find bugs", "test and fix" | Three tiers: Quick, Standard, Exhaustive
`/qa-only`: report-only QA — health score, screenshots, repro steps, no code fixes
`/benchmark`: performance regression detection — Core Web Vitals, load times, bundle size
`/scrape`: pull structured data from a web page
`/setup-browser-cookies`: import Chromium cookies for authenticated QA sessions

### Security (gstack)
`/cso`: Chief Security Officer — OWASP Top 10, STRIDE, secrets archaeology, supply chain, LLM security | "security audit", "threat model" | Invoke for any change to `security/` or credential handling

### Debugging (gstack)
`/investigate`: systematic root cause analysis | "debug this", "why is this broken", "root cause"

### Shipping & Deploy (gstack)
`/review`: pre-landing PR diff review — trust boundaries, conditional side effects | Invoke before merge
`/ship`: ship workflow — merge base, test, review diff, bump `VERSION`, update `CHANGELOG.md`, commit, push, PR
`/land-and-deploy`: merge PR, wait for CI, verify health via canary
`/babysit`: keep a PR merge-ready — triage comments, resolve conflicts, fix CI in a loop
`/split-to-prs`: split a large change set into small reviewable PRs
`/canary`: post-deploy monitoring
`/document-release`: post-ship docs sync — README, CHANGELOG, `.agents/repo-docs/`
`/document-generate`: generate missing docs for a module or feature
`/retro`: weekly engineering retrospective
`/health`: code quality dashboard
`/learn`: record project learnings

### Safety Modes (gstack)
`/careful`: warns before destructive commands (`rm -rf`, force-push) | "be careful", "prod mode"
`/freeze`: restrict edits to one directory for the session
`/guard`: full safety mode (careful + freeze)
`/unfreeze`: clear the freeze boundary

### Second Opinion & Maintenance (gstack)
`/codex`: OpenAI Codex review, challenge, or consult modes — independent second opinion
`/gstack-upgrade`: upgrade gstack to the latest version

### Cursor Configuration & Artifacts
`/create-rule`, `/create-skill`, `/create-hook`, `/automate`, `/statusline`, `/update-cursor-settings`: author Cursor rules, skills, hooks, automations, and settings
`okf-docs` (canonical: `.agents/skills/okf-docs/`; also via `.cursor/skills`, `.claude/skills`, `.codex/skills` symlinks): OKF v0.2 docs authoring — frontmatter, `docs/` bundle, `.agents/repo-docs/`. Invoke when adding/editing docs, writing OKF metadata, or migrating documentation.
`/canvas`, `/docs-canvas`, `/pr-review-canvas`: render analytical artifacts, docs overviews, or PR walkthroughs as a Cursor Canvas
`/diagram`, `/make-pdf`: diagrams from English or mermaid; publication-quality PDFs from markdown
`/sdk`: the **Cursor** SDK (`@cursor/sdk` / `cursor-sdk`) | NOT: the HarnessBox Python SDK in `packages/sdk/`

## Commit Message Format

Use conventional commits: `<type>(<scope>): <description>`

- Types: `feat`, `fix`, `refactor`, `test`, `chore`, `docs`, `style`.
- Scope: the module or package name (e.g., `feat(streaming): add event deduplication`, `fix(sdk): resolve mypy unused ignores`, `feat(hbox): add interactive CLI`).
- Body: include the linked GitHub issue number (`Closes #<issue_number>`) when applicable.
- Never use generic messages like "fix bug" or "update code".
- Never add self-attributed author credits like `authored by` or `co-authored by claude code`.

## PR review gating

Once a PR is created, wait for GitHub Copilot's review comments and address them before merging.
After the Copilot comments are resolved, run the `/review` skill (or the Bugbot subagent for a diff-focused pass).
If issues are identified, fix and commit them, then wait for the user to either confirm the merge or surface new review comments to work through.

## Error Recovery Protocol

- **CI failure**: Analyze the failing step's logs and fix the root cause. Never suppress a linter error with `# noqa` (or `// eslint-disable`) without a comment explaining why it is correct.
- **Type errors from mypy**: Fix the type. Do not use `# type: ignore` unless the library genuinely lacks stubs — and add a comment saying so. Also remove ignores that have become unnecessary; `mypy` strict mode flags them.
- **Failing pytest**: Never skip a test. If a test is genuinely obsolete, ask the user before deleting it.
- **Flaky infra-dependent tests**: E2E tests need `E2B_API_KEY`; a skip is not a pass. If a test needs real infrastructure, it belongs in `tests/e2e/` with the `e2e` marker.
- **Coverage gate failure**: Add real tests for the new code path. Do not lower the coverage threshold.
- **Web build failures**: Run `bun run build` (which runs `tsc -b` first) locally before opening the PR.

## Task Completion Checklist

Before marking any task done, confirm:

- [ ] GitHub Issue is created and linked to the PR (when applicable)
- [ ] SDK lint and format pass (`uv run ruff check .`, `uv run ruff format --check .`)
- [ ] SDK types pass (`uv run mypy .`)
- [ ] New logic has at least one corresponding pytest, in the right tier (`unit/`, `integration/`, `contract/`, `e2e/`)
- [ ] Full SDK suite passes (`uv run pytest tests/ -v`)
- [ ] Web app builds and tests pass if `apps/web/` changed (`bun run build`, `bun run test`)
- [ ] Docs updated when behavior changed — the affected `.agents/repo-docs/` file, `README.md`, and `CHANGELOG.md`
- [ ] PR description includes: what changed, why, and how to test it
- [ ] No secrets, debug prints, `console.log`, or leftover `TODO`s in committed code

## Project Overview

HarnessBox is a platform for running AI coding agents in secure sandbox environments. The Python SDK provisions a sandbox, clones a git repo into it, runs an agent harness (Claude Code, Codex, OpenCode) under a security policy, and streams the agent's output as typed events. Idle workspaces auto-pause to $0/hr and resume transparently on the next message.

The SDK is the product. Everything else is a deployment choice: import it directly for scripts and services, or run `harnessbox serve` to get the same SDK behind HTTP/SSE with shared state across clients (think SQLite vs Postgres).

Read `CONTEXT.md` for the domain glossary before naming anything. The short version: a **Sandbox** is the VM, a **Workspace** is a sandbox bound to a git repo, a **Session** is one agent conversation within a workspace, and **HarnessBox** is the orchestrator and sole public API surface.

## Architecture — File Index

**Monorepo**: `packages/sdk/` (Python SDK, PyPI `harnessbox`, currently 0.3.0) + `apps/web/` (React/Vite dashboard) + `apps/api/` (cloud API: Supabase auth, Stripe billing, teams) + `apps/desktop/`, `apps/site/` (stubs, `.gitkeep` only).

Use this index to jump directly to files. For design rationale and extension points, see [`.agents/repo-docs/`](.agents/repo-docs/) listed at the bottom.

### SDK public surface (`packages/sdk/src/harnessbox/`)

| Path | Purpose |
|------|---------|
| `__init__.py` | Public exports: `HarnessBox`, `Sandbox`, `SecurityPolicy`, streaming types, credentials, lifecycle, config helpers; lazy `HarnessBoxClient` |
| `harnessbox.py` | `HarnessBox` entry point — `create_session()`, `Session` handle, `Snapshot`, `HarnessBoxSecrets`, `WorkspaceConfig`; delegates to `Sandbox` |
| `client.py` | `HarnessBoxClient` — HTTP/SSE client for a remote server; `WorkspaceInfo`, create-wait hooks, workspace CRUD, prompt streaming |
| `providers.py` | `SandboxProvider` protocol, `CommandResult`, `SandboxDeadError`, optional capability protocols (PTY, native git) |
| `workspace.py` | `Workspace` protocol, `GitRepoConfig` (clone/commit/push/status), `GitStatus`, `GitBranchAlreadyExistsError` |
| `streaming.py` | `UniversalEvent`, `StreamParser`, `EventType`/`ItemKind` enums — NDJSON `stream-json` → UI-oriented events |
| `lifecycle.py` | `RuntimeState` (incl. `PAUSED`, `ERROR`), `VALID_RUNTIME_TRANSITIONS`, `validate_runtime_transition` |
| `credentials.py` | Host-side `detect_credentials()`, `CredentialProbe`/`CredentialStatus`, auth-mode detection — never exposes secret values |
| `types.py` | `AgentResponse` — non-streaming turn result (text, cost, events) |
| `cost.py` | `CostMetrics`, `ModelCost`, `parse_cost_data()` — aggregates agent `/cost` output |
| `status.py` | `parse_context_output()` — parses agent `/context` markdown into token/model usage |
| `names.py` | `generate_workspace_name()` — memorable city-name workspace identifiers |
| `_version.py` | `__version__` |

### SDK orchestration internals

| Path | Purpose |
|------|---------|
| `sandbox.py` | `Sandbox` orchestrator — `setup()` via `initialize_sandbox`, `send_message`, `run_command`, pause/resume/kill |
| `process.py` | `AgentProcess` — persistent CLI subprocess in the sandbox; stdin JSON prompts, NDJSON stdout, permission responses |
| `events.py` | `EventBuffer` — per-session ring buffer (1024) with async fan-out for SSE replay via `Last-Event-ID` |
| `_internal/runtime.py` | `AgentRuntime` — agent process lifecycle, streaming turns, `InteractiveSession` PTY wrapper |
| `_internal/session.py` | `SandboxSession` — `RuntimeState` transitions, idle coordination hooks, pause/resume/snapshot events |
| `_internal/workspace_mount.py` | `WorkspaceMount` — builds `InitializeContext` (files, env, git, fs) and the runtime git facade |
| `_providers/__init__.py` | Provider registry — `get_provider_class`, `register_provider`, `list_providers` (lazy; `e2b` → `E2BProvider`) |
| `_providers/e2b.py` | `E2BProvider` — `AsyncSandbox` wrapper with native git API, PTY, egress probe on resume, dead-sandbox detection |
| `_utils/timing.py` | `@timed_operation` async decorator for debug timing logs |

### Config & security

| Path | Purpose |
|------|---------|
| `config/harness.py` | `HarnessTypeConfig` registry + `register_harness_type` — how each agent type is invoked (CLI flags, config dir, settings builder) |
| `config/manifest.py` | `build_manifest()` → `SandboxManifest` — pure computation of every file, dir, and env var to inject |
| `config/pipeline.py` | `initialize_sandbox()` — `InitializeContext`, `FileSystemSpec`, ordered setup steps |
| `config/project.py` | `load_project_config()` for `.harnessbox.toml` — presets, custom agents, merge into init context |
| `security/policy.py` | `SecurityPolicy`, `build_settings()`, `resolve_credential_guards()` — deny rules and generated `settings.json` |
| `security/guards.py` | `CredentialGuardSet` + `GUARD_CATALOG` (10 sets) — single source of truth for deny globs and hook regexes |
| `security/hooks.py` | `build_guard_script()` — PreToolUse hook script generated from guard regexes (fail-open) |
| `security/events.py` | `SandboxEvent`, `EventHandler`, `CallbackHandler`, `JsonLogger` for sandbox observability |

### Server (`_server/`) and CLIs

| Path | Purpose |
|------|---------|
| `server.py` | `create_app()` FastAPI factory — routers, CORS, `WorkspaceManager` lifespan, SQLite default via `HARNESSBOX_*` env |
| `_server/workspace_manager.py` | `WorkspaceManager` facade — registry + idle + session routing + event replay + graceful shutdown |
| `_server/registry.py` | `WorkspaceRegistry` — in-memory workspace map, create/hydrate/reconnect, `WorkspaceConfig`/`WorkspaceInstance` |
| `_server/session_router.py` | `SessionRouter` — the prompt path: conversations, attachments, agent dispatch, event persistence, turn boundaries |
| `_server/agent_manager.py` | `AgentManager` — one `AgentProcess` per `conversation_id`, with `--resume` recovery |
| `_server/event_replay.py` | `EventReplay` — storage-backed gap fill, then handoff to the live `EventBuffer` |
| `_server/idle.py` | `IdleOrchestrator` — per-workspace idle timers, auto-pause when no turns are active |
| `_server/workspace_factory.py` | Maps HTTP create requests → `WorkspaceConfig`; host env injection, git detection helpers |
| `_server/storage.py` | `StorageBackend` protocol — workspace/conversation/event persistence contract |
| `_server/_storage/sqlite.py` | `SQLiteBackend` — persistent storage with `MigrationRunner` |
| `_server/_storage/memory.py` | `MemoryBackend` — in-process dict storage for tests and ephemeral use |
| `_server/_storage/migrations/` | Forward-only schema history v001–v006 (initial schema, event-type index, state split, legacy-status drop, conversation `agent_session_id`, workflow/PR column drop) |
| `_server/routers/sessions.py` | Main API surface — workspace lifecycle, files, conversations, prompt/SSE, events, history, permissions |
| `_server/routers/discovery.py` | Discovery endpoints — credentials status, harnesses, providers, guards |
| `_server/routers/workspace.py` | Workspace name generation and local git repo detection |
| `_server/routers/account.py` | GitHub account info via the local `gh` CLI |
| `_server/routers/_models.py` | Pydantic request/response models for the HTTP API |
| `_server/routers/_deps.py` | FastAPI dependencies — `get_manager()`, `workspace_response()` |
| `cli.py` | `harnessbox` console entry — `harnessbox serve` (uvicorn + `create_app`) |
| `hbox/app.py` | `hbox` interactive REPL — slash commands, local config, `HarnessBoxClient` + `ServerManager` |
| `hbox/server_manager.py` | `ServerManager` — probe/spawn/stop a local `harnessbox serve`, `~/.harnessbox/server.json` |
| `hbox/ui.py` | `CreateProgress`, turn event formatting, model warnings (rich + plain fallback) |

### HTTP API surface

All routes are versioned under `/v1`. Workspace IDs are the session identity on the wire — there is no `/v1/sessions/*` tree.

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/v1/workspaces/create` | Create workspace (202, async provisioning); `POST /v1/workspaces` is a deprecated alias |
| GET / GET / DELETE | `/v1/workspaces`, `/v1/workspaces/{id}`, `/v1/workspaces/{id}` | List, get, destroy (204) |
| POST | `/v1/workspaces/{id}/prompt` | Send a prompt, SSE stream of `UniversalEvent`s |
| GET | `/v1/workspaces/{id}/events` | Live SSE stream (replay via `Last-Event-ID`) |
| GET | `/v1/workspaces/{id}/history`, `/events.jsonl` | Historical SSE stream; JSONL export |
| POST | `/v1/workspaces/{id}/pause`, `/resume`, `/stop`, `/retry` | Lifecycle control; `retry` reprovisions from `ERROR` |
| POST | `/v1/workspaces/{id}/files`, `/permission` | Upload files (204); respond to a permission request |
| GET | `/v1/credentials/status`, `/v1/harnesses`, `/v1/providers`, `/v1/guards` | Discovery |
| GET | `/v1/workspace/name`, `/v1/workspace/detect`, `/v1/account/github` | Helpers |

### Web app (`apps/web/`)

React 19 + TanStack Router/Query + Vite 8 + Tailwind v4 (shadcn-style primitives), Vitest, oxlint, TypeScript.

| Path | Purpose |
|------|---------|
| `src/main.tsx` | React root — `QueryClientProvider` + `RouterProvider` |
| `src/router.tsx` | Routes: `/` board, `/session/$sessionId`, `/settings`, `/test-cost-viz` |
| `src/pages/` | `board`, `session`, `settings`, `test-cost-viz` page shells |
| `src/components/layout/` | `app-layout`, sidebars, header, add-repo dialog |
| `src/components/session/` | New session, config, creating state, `session-view` |
| `src/components/session-board/` | Kanban-style session board app |
| `src/components/event/` | Event rendering — markdown, tool calls, permission prompts, user messages |
| `src/components/metrics/` | `CostTracker`, `ContextTracker`, session metrics menu |
| `src/components/ui/` | shadcn/Radix-style primitives |
| `src/hooks/` | `use-session-manager`, `use-discovery`, `use-credentials`, `use-github-profile`, `use-local-storage`, `use-mobile` |
| `src/lib/api.ts` | REST client for the proxied `/api/v1/*` surface |
| `src/lib/sse.ts` | SSE helpers for event streams |
| `src/lib/sessions/` | Reducer, types, `SessionConnections`, board columns, client utils |
| `src/lib/events/grouping.ts` | Groups universal events for the feed UI |
| `src/lib/storage.ts`, `storage-schema.ts` | Local persistence of UI state |
| `src/types.ts` | Shared types aligned with the SDK's API models |

### Cloud API (`apps/api/`)

| Path | Purpose |
|------|---------|
| `src/harnessbox_api/main.py` | `create_app()` — mounts the SDK routers plus cloud routes |
| `src/harnessbox_api/auth.py`, `routes/auth_routes.py` | Supabase auth + JWT verification |
| `src/harnessbox_api/billing.py`, `routes/billing_routes.py` | Stripe billing |
| `src/harnessbox_api/routes/teams_routes.py` | Team management |
| `src/harnessbox_api/config.py` | `pydantic-settings` configuration |

### Tests (`packages/sdk/tests/`)

| Path | Purpose |
|------|---------|
| `conftest.py` | `MockProvider` — in-memory `SandboxProvider` recording commands, files, and state; no VM is created |
| `unit/` | Single-module tests, auto-marked `unit` |
| `integration/` | Multi-component: sandbox, streaming, pipeline, server; auto-marked `integration` |
| `integration/_server/` | `WorkspaceManager`, storage, migrations, agent manager, idle timer |
| `contract/` | `SandboxProvider` behavioral contract, parametrized `mock` + `e2b` (E2B skipped without a key) |
| `e2e/` | Real E2B infrastructure, marked `e2e`, skipped entirely without `E2B_API_KEY` |
| `fixtures/` | Recorded NDJSON turns for stream parser tests |

### Deep-Dive Docs (read on demand)

When creating or editing documentation, read and follow [`.agents/skills/okf-docs/SKILL.md`](.agents/skills/okf-docs/SKILL.md) first.

Agent deep-dives live in [`.agents/repo-docs/`](.agents/repo-docs/) (OKF-style YAML frontmatter; outside the user-facing `docs/` OKF bundle). Read the relevant file before detailed work in that area:

- **Developer Commands & Workspace Setup** → [commands.md](.agents/repo-docs/commands.md) when building, running, testing, or syncing dependencies.
- **Safety, Guards & Development Rules** → [rules.md](.agents/repo-docs/rules.md) before touching sandbox providers, security guards, or credentials.
- **Architecture & Module Responsibilities** → [architecture.md](.agents/repo-docs/architecture.md) for core flows, design decisions, and extension points (adding a provider or harness type).
- **Coding Conventions, Commits & CI Policies** → [conventions.md](.agents/repo-docs/conventions.md) for formatting, test invariants, and CI recovery.
- **Issue Tracking, Labels & Domain Language** → [issue-tracker.md](.agents/repo-docs/issue-tracker.md), [triage-labels.md](.agents/repo-docs/triage-labels.md), [domain.md](.agents/repo-docs/domain.md), and `CONTEXT.md`.
- **Sandbox subsystem docs** → `docs/sandboxes/` (overview, security, commands, snapshots, streaming, workspaces) — OKF bundle under [`docs/`](docs/index.md).
- **User-facing docs** → `docs/getting-started/` (introduction, quickstart, how-it-works) and `docs/openapi.yaml`.
- **Runnable examples** → `packages/sdk/examples/quickstart.py`, `packages/sdk/examples/multi_session.py`.

## Development Commands

### SDK (`packages/sdk/`)

```bash
cd packages/sdk

uv sync                                              # Install all dependencies
uv run pytest tests/ -v                              # Full suite (fast — MockProvider, no real sandboxes)
uv run pytest tests/integration/test_stream_parser.py -v          # Single file
uv run pytest tests/unit/test_guards.py::TestMergeGuardSets -v    # Single class or test
uv run pytest -m "not e2e" -v                        # Deselect real-infrastructure tests
uv run ruff check .                                  # Lint
uv run ruff format --check .                         # Format check
uv run mypy .                                        # Type check (strict for source, relaxed for tests)

# Full local CI check
uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest tests/ -v
```

### Server & CLI

```bash
harnessbox serve --port 8000     # HTTP/SSE server (env: HARNESSBOX_PORT, --db PATH)
hbox                             # Interactive REPL (spawns a local server if needed)
python -m harnessbox.hbox        # Equivalent module entry point
```

### Web app (`apps/web/`)

```bash
cd apps/web

bun install       # or: npm ci
bun run dev       # Vite dev server (proxies /api → http://localhost:8000)
bun run build     # tsc -b + production build
bun run test      # Vitest
bun run lint      # oxlint
bunx tsc --noEmit # Type check only
```

## Key Conventions

- **Python**: 3.12+ (CI also runs 3.13), async throughout, **stdlib only at runtime**. Managed with `uv` — never call `pip` directly. Ruff with line length 100 (E501 ignored). Mypy strict for `harnessbox/`, relaxed for `tests/`.
- **Public vs internal**: Users touch `HarnessBox`, `Session`, and configuration types only. `Sandbox`, `WorkspaceManager`, and anything under `_internal/`, `_providers/`, `_server/` are implementation details — do not widen their exposure.
- **Extensibility via protocols**: `SandboxProvider` and `Workspace` are `Protocol` classes (structural typing), not ABCs. A new provider must implement the full surface, register itself in `_providers/__init__.py`, and add its dependency as an optional extra in `packages/sdk/pyproject.toml`. A new harness type registers via `register_harness_type(HarnessTypeConfig(...))`.
- **Security invariants**: credentials never travel as environment variables (git auth uses a credential helper); each `CredentialGuardSet` defines its deny globs and hook regexes together as one source of truth; `build_manifest()` is pure computation with no I/O; PreToolUse hooks fail open, prioritizing availability.
- **Server behavior**: the server always mints `workspace_id` (client-supplied IDs are ignored); when git is configured, the agent's cwd is `/workspace/<clone_dir_name>` regardless of the requested `cwd`.
- **Storage**: SQLite by default, `MemoryBackend` for tests. Migrations are forward-only and append-only.
- **Tests**: `pytest` with `asyncio_mode = "auto"` and markers `unit`, `integration`, `contract`, `e2e`. Everything except `e2e/` runs against `MockProvider` — never write a test that needs real sandbox infrastructure outside `tests/e2e/`.
- **TypeScript**: strict mode, Tailwind v4, path alias `@/` → `apps/web/src/`. Keep API types in `src/types.ts` in sync with `_server/routers/_models.py`.
- **Versioning**: `VERSION` at the repo root and `_version.py` in the SDK both carry the release version; `CHANGELOG.md` is updated on ship.
