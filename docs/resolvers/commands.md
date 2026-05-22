# Resolver: Developer Commands

This resolver contains the setup, build, lint, and test commands for both the Python SDK and the Web Application. Read this file when you need to run tasks, check types, run lints, or execute tests.

## Commands

### SDK (`sdk/`)

```bash
cd sdk
uv sync                          # Install all dependencies
uv run pytest tests/ -v          # Run all tests (~0.2s, uses MockProvider)
uv run pytest tests/integration/test_sandbox.py -v                                    # Single file
uv run pytest tests/unit/test_workspace.py::TestGitRepoConfigInject::test_clone_public_repo -v  # Single test
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

## CI Pipeline

CI runs lint → type check → tests on PRs targeting main.
