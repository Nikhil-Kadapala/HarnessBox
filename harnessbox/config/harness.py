"""Harness type registry — declarative config for Claude Code, Codex, OpenCode, Gemini CLI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from harnessbox.security.policy import SecurityPolicy


@dataclass(frozen=True)
class HarnessTypeConfig:
    """Declarative configuration for a harness type.

    Describes how to set up and invoke a specific AI coding agent
    inside a sandbox.
    """

    name: str
    config_dir: str
    settings_file: str | None
    hooks_dir: str | None
    system_prompt_file: str
    default_dirs: tuple[str, ...]
    cli_command: str
    cli_oneshot_template: str
    cli_interactive_template: str
    workspace_root: str = "/workspace"
    build_settings: Callable[[SecurityPolicy], dict[str, Any]] | None = None
    build_hook_script: Callable[[], str] | None = None


_HARNESS_REGISTRY: dict[str, HarnessTypeConfig] = {}


def register_harness_type(config: HarnessTypeConfig) -> None:
    """Register a harness type configuration."""
    _HARNESS_REGISTRY[config.name] = config


def get_harness_type(name: str) -> HarnessTypeConfig:
    """Look up a harness type by name. Raises KeyError if not found."""
    if name not in _HARNESS_REGISTRY:
        registered = ", ".join(sorted(_HARNESS_REGISTRY)) or "(none)"
        raise KeyError(f"Unknown harness type {name!r}. Registered types: {registered}")
    return _HARNESS_REGISTRY[name]


def list_harness_types() -> list[str]:
    """Return names of all registered harness types."""
    return sorted(_HARNESS_REGISTRY)


# ---------------------------------------------------------------------------
# Built-in harness types
# ---------------------------------------------------------------------------


def _claude_code_build_settings(policy: SecurityPolicy) -> dict[str, Any]:
    from harnessbox.security.policy import build_settings

    return build_settings(policy)


def _claude_code_build_hook() -> str:
    from harnessbox.security.hooks import GUARD_BASH_SCRIPT

    return GUARD_BASH_SCRIPT


register_harness_type(
    HarnessTypeConfig(
        name="claude-code",
        config_dir=".claude",
        settings_file=".claude/settings.json",
        hooks_dir=".claude/hooks",
        system_prompt_file="CLAUDE.md",
        default_dirs=("/workspace/user_input", "/workspace/output"),
        cli_command="claude",
        cli_oneshot_template=(
            "claude --dangerously-skip-permissions"
            " --output-format stream-json"
            " --verbose"
            " -p {prompt}"
        ),
        cli_interactive_template=(
            "claude --dangerously-skip-permissions --output-format stream-json --verbose"
        ),
        build_settings=_claude_code_build_settings,
        build_hook_script=_claude_code_build_hook,
    )
)

register_harness_type(
    HarnessTypeConfig(
        name="codex",
        config_dir=".codex",
        settings_file=None,
        hooks_dir=None,
        system_prompt_file="AGENTS.md",
        default_dirs=("/workspace",),
        cli_command="codex",
        cli_oneshot_template="codex --model o4-mini -q {prompt}",
        cli_interactive_template="codex --model o4-mini",
    )
)

register_harness_type(
    HarnessTypeConfig(
        name="gemini-cli",
        config_dir=".gemini",
        settings_file=None,
        hooks_dir=None,
        system_prompt_file="GEMINI.md",
        default_dirs=("/workspace",),
        cli_command="gemini",
        cli_oneshot_template="gemini -p {prompt}",
        cli_interactive_template="gemini",
    )
)

register_harness_type(
    HarnessTypeConfig(
        name="opencode",
        config_dir=".opencode",
        settings_file=None,
        hooks_dir=None,
        system_prompt_file="AGENTS.md",
        default_dirs=("/workspace",),
        cli_command="opencode",
        cli_oneshot_template="opencode -p {prompt}",
        cli_interactive_template="opencode",
    )
)
