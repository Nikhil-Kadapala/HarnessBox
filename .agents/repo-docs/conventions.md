---
type: Repo Doc
title: Coding Conventions, Commits & CI
description: Python/TS conventions, test invariants, conventional commits, and CI merge policy.
tags: [sdk, ci, agent]
status: stable
generated: { by: process:okf-migration, at: 2026-07-27T19:33:00Z }
---

# Coding Conventions, Commits & CI

Read this before formatting code, writing tests, creating commits, or handling CI errors.

## Code & Type Conventions

- Python 3.12+ (CI also runs 3.13), async throughout, **stdlib only at runtime**.
- Ruff: line length 100, E501 ignored.
- Mypy: strict for `harnessbox/`, relaxed for `tests/`.
- `uv` for dependency management (never call `pip` directly).
- TypeScript: strict mode; path alias `@/` → `apps/web/src/`.

## Testing Invariants

- Default suite uses `MockProvider` from `packages/sdk/tests/conftest.py` — no real VMs.
- Markers: `unit`, `integration`, `contract`, `e2e`.
- Never write tests that need real sandbox infrastructure outside `tests/e2e/` (marked `e2e`, skipped without `E2B_API_KEY`).
- Contract tests may parametrize `mock` + `e2b`; E2B skips without a key.

## Commit Message Format

Use conventional commits: `<type>(<scope>): <description>`

- Types: `feat`, `fix`, `refactor`, `test`, `chore`, `docs`, `style`
- Scope: module or package name (e.g. `feat(streaming): add event deduplication`)
- Body: include `Closes #<issue_number>` when applicable
- Never use generic messages like "fix bug"
- Never add self-attributed author credits like `co-authored by claude code`

## CI & Merge Policy

- PR CI must pass before merge — no bypassing failed checks.
- Always use **merge commits** (not squash or rebase).
- No force-merges past conflicts or failed checks.

## Error Recovery Protocol

- **CI failure**: Fix the root cause; never suppress linter errors with bare `# noqa` without a justifying comment.
- **mypy**: Fix the type; `# type: ignore` only when stubs are missing, with a comment.
- **Failing pytest**: Never skip a test. Ask before deleting an obsolete test.
- **Coverage gate**: Add real tests; do not lower the threshold.
