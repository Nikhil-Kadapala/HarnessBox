---
type: Repo Doc
title: Developer Commands
description: Setup, lint, type-check, and test commands for the SDK and web app.
tags: [sdk, web, ci]
status: stable
generated: { by: process:okf-migration, at: 2026-07-27T19:33:00Z }
---

# Developer Commands

Read this when you need to run tasks, check types, run lints, or execute tests.

## SDK (`packages/sdk/`)

```bash
cd packages/sdk
uv sync                          # Install all dependencies
uv run pytest tests/ -v          # Full suite (MockProvider; no real sandboxes)
uv run pytest tests/integration/test_sandbox.py -v
uv run pytest tests/unit/test_guards.py::TestMergeGuardSets -v
uv run ruff check .
uv run ruff format --check .
uv run mypy .
# Full local CI check
uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest tests/ -v
```

E2E tests under `tests/e2e/` need `E2B_API_KEY` and are skipped without it.

## Web App (`apps/web/`)

```bash
cd apps/web
bun install
bun run dev                      # Vite (proxies /api → localhost:8000)
bun run build                    # tsc -b + production build
bun run test                     # Vitest
bun run lint                     # oxlint
bunx tsc --noEmit
```

## Server & CLI

```bash
harnessbox serve --port 8000
hbox
python -m harnessbox.hbox
```

## CI Pipeline

`.github/workflows/ci.yml` runs on push and PR to `main`, scoped to `packages/sdk`: lint/format/mypy/bandit/pip-audit, then pytest on Python 3.12 and 3.13. CI does not currently build `apps/web` or `apps/api`.
