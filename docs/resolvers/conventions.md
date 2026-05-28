# Resolver: Coding Conventions, Commits & CI

This resolver contains the development standards, python styling rules, test invariants, git commit messages, and CI/merge policies. Read this file before formatting code, writing tests, creating commits, or handling CI errors.

## Code & Type Conventions

- Python 3.12+, async throughout, stdlib only at runtime.
- Ruff: line length 100, E501 ignored.
- Mypy: strict mode for `harnessbox/`, relaxed mode for `tests/`.
- `uv` for dependency management (do not use pip directly).

## Testing Invariants

All tests use `MockProvider` from `packages/sdk/tests/conftest.py` — an in-memory provider that tracks commands, files, and state. No real sandboxes are created. Tests are fast (~0.2s total). Never write tests that require real sandbox infrastructure unless they are in `tests/integration/` and explicitly marked.

## Commit Message Format

Use conventional commits: `<type>(<scope>): <description>`
- Types: `feat`, `fix`, `refactor`, `test`, `chore`, `docs`
- Scope: use the module name (e.g., `feat(streaming): add event deduplication`)
- Body: include the linked GitHub issue number (`Closes #<issue_number>`) when applicable.
- Never use generic messages like "fix bug" or "update code".
- Never add self-attributed author credits like `co-authored by claude code`.

## CI & Merge Policy

- PR CI must pass before merge — no bypassing failed checks.
- Always use **merge commits** (not squash or rebase) so the exact commits that passed CI land on `main` unchanged.
- No force-merges past conflicts or failed checks.

## Error Recovery Protocol

- **CI failure**: Analyze the failing step. Fix the root cause; never suppress linter errors with `# noqa` without a comment explaining why.
- **Type errors from mypy**: Fix the type; do not use `# type: ignore` unless the library lacks stubs (and add a comment explaining why if so).
- **Failing pytest**: Never skip tests. If a test is genuinely obsolete, ask the user before deleting it.
