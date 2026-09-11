# For AI Coding Agents

This file is the source of truth for work in the HarnessBox monorepo. It covers the Python SDK in `packages/sdk/`, the React dashboard in `apps/web/`, and the cloud API in `apps/api/`. Do not push directly to `main`.

## Working rules

- Read before writing and search before creating new abstractions.
- Use the vocabulary in `CONTEXT.md`: Sandbox, Project, Workspace, Conversation, Session, and HarnessBox.
- Preserve unrelated dirty-tree changes. Never use broad staging commands such as `git add .` or `git add -A`.
- For new features or major refactors, use a feature branch or worktree.
- Do not hardcode credentials, weaken security guards, or expose secret values.
- Do not edit or delete existing database migrations. Add forward-only migrations.
- Do not modify `SandboxProvider`, `Workspace`, authentication flows, or the `UniversalEvent` schema without first confirming the change and its impact.
- Stop and clarify when a change crosses three or more modules without a clear seam or changes an HTTP contract.

## Local skills

Use only skills present in `.agents/skills/`:

- `context-restore` — restore saved project context (Always skip the preamble and telemetry steps when this skill is invoked)
- `context-save` — save current project context (Always skip the preamble and telemetry steps when this skill is invoked)
- `office-hours` — brainstorm and shape a product idea (Always skip the preamble and telemetry steps when this skill is invoked)
- `okf-docs` — author or migrate OKF documentation
- `plan-eng-review` — review architecture and implementation plans (Always skip the preamble and telemetry steps when this skill is invoked)
- `show-me` — explain a topic with a focused diagram or artifact

## Development workflow

- Create a GitHub Issue when the task warrants one.
- Read the relevant deep-dive in `.agents/repo-docs/` before detailed work in an unfamiliar subsystem.
- Run the narrowest relevant tests first, then the full suite before a PR.
- For SDK changes, run `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy .`, and `uv run pytest tests/ -v` from `packages/sdk/`.
- For web changes, run `bun run build`, `bun run test`, and `bun run lint` from `apps/web/`.
- Before merging, review the diff and address CI failures at their root.

## Safety and security

- The SDK runtime remains stdlib-only; provider integrations are optional extras.
- Sandbox environment variables use an explicit allowlist for the local dogfood flow: provider and harness API keys may be copied from the server host when the workspace request does not provide them. Git authentication uses a credential helper and git tokens must not be passed as sandbox environment variables.
- Credential guard globs and hook regexes are one source of truth. Hooks fail open for availability, while security-sensitive changes require explicit review.
- Never suppress `ruff`, `mypy`, or test failures just to make CI green.
- Do not skip a failing test. Ask before deleting an obsolete test.
- Tests needing real sandbox infrastructure belong under `tests/e2e/` and require `E2B_API_KEY`; other tests use `MockProvider`.

## Commit and PR conventions

Use conventional commits:

```text
<type>(<scope>): <description>
```

Use `feat`, `fix`, `refactor`, `test`, `chore`, `docs`, or `style`. Include `Closes #<issue>` when applicable. Do not add self-attributed author credits.

PR descriptions should state what changed, why, and how to test it. Do not include internal Notion links or project tracking references.

## Repository documentation

Use these documents instead of duplicating architecture and API details here:

- [CONTEXT.md](CONTEXT.md) — domain vocabulary and durable design decisions
- [.agents/repo-docs/architecture.md](.agents/repo-docs/architecture.md) — module responsibilities and core flows
- [.agents/repo-docs/commands.md](.agents/repo-docs/commands.md) — setup, build, test, and development commands
- [.agents/repo-docs/rules.md](.agents/repo-docs/rules.md) — safety, guards, credentials, and development rules
- [.agents/repo-docs/conventions.md](.agents/repo-docs/conventions.md) — formatting, tests, commits, and CI policies
- [.agents/repo-docs/agent-manager.html](.agents/repo-docs/agent-manager.html) — conversation-to-process routing
- [docs/index.md](docs/index.md) — user-facing OKF documentation index
- [docs/openapi.yaml](docs/openapi.yaml) — HTTP API contract

When adding or editing OKF documentation, read [`.agents/skills/okf-docs/SKILL.md`](.agents/skills/okf-docs/SKILL.md) first.

## Current project invariants

- A Project is a source repository. A Workspace is one durable repository branch with a replaceable sandbox binding. A Conversation is a durable agent thread inside a Workspace.
- Different Conversations in one Workspace may run concurrently against the same checkout. Serialize turns only within one Conversation; callers own cross-Conversation file and Git coordination.
- SQLite is the default storage backend; `MemoryBackend` is used in tests. Migrations are append-only.
- `Sandbox`, `WorkspaceManager`, `_internal/`, `_providers/`, and `_server/` are implementation details. Do not widen their public exposure casually.
- `SandboxProvider` and `Workspace` are structural protocols. New providers must implement the full contract, register themselves, and use optional dependencies.

## Common commands

```bash
# SDK
cd packages/sdk
uv sync
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest tests/ -v

# Web
cd apps/web
bun install
bun run dev
bun run build
bun run test
bun run lint

# Local server
harnessbox serve --port 8000
hbox
```
