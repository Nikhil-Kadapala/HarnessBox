# Contributing to HarnessBox

Thanks for your interest in contributing. HarnessBox is an early-stage project and we welcome contributions of all kinds.

## Development Setup

```bash
# Clone the repo
git clone https://github.com/Nikhil-Kadapala/HarnessBox.git
cd HarnessBox

# Install uv (if you don't have it)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync

# Run tests
uv run pytest tests/ -v

# Lint
uv run ruff check .

# Type check
uv run mypy .
```

## Running Tests

All tests use a `MockProvider` (no real sandbox needed). Tests run in ~0.1s.

```bash
# All tests
uv run pytest tests/ -v

# Specific test file
uv run pytest tests/test_workspace.py -v

# Specific test
uv run pytest tests/test_workspace.py::TestGitWorkspaceInject::test_clone_public_repo -v
```

## Code Style

- Python 3.12+
- Ruff for linting (line length 100)
- Mypy strict mode for source, relaxed for tests
- No runtime dependencies (stdlib only)
- Provider SDKs are optional extras

## Submitting Changes

1. Fork the repo
2. Create a branch (`git checkout -b feat/my-feature`)
3. Make your changes
4. Run `uv run ruff check . && uv run mypy . && uv run pytest tests/ -v`
5. Commit with conventional commits (`feat:`, `fix:`, `docs:`, `test:`)
6. Open a PR against `main`

## Adding a New Provider

Providers live in `harnessbox/_providers/`. To add one:

1. Create `harnessbox/_providers/yourprovider.py`
2. Implement the `SandboxProvider` protocol (see `providers.py`)
3. Register it in `harnessbox/_providers/__init__.py`
4. Add tests in `tests/test_providers.py`
5. Add an optional dependency in `pyproject.toml`

## Adding a New Harness Type

Harness types are registered in `harnessbox/config/harness.py`:

```python
register_harness_type(HarnessTypeConfig(
    name="my-agent",
    config_dir=".myagent",
    settings_file=None,
    hooks_dir=None,
    system_prompt_file="SYSTEM.md",
    default_dirs=("/workspace",),
    cli_command="myagent",
    cli_oneshot_template="myagent run {prompt}",
    cli_interactive_template="myagent",
))
```

## Reporting Issues

- Use GitHub Issues
- Include: what you expected, what happened, reproduction steps
- For security issues, see `SECURITY.md`

## License

By contributing, you agree that your contributions will be licensed under MIT.
