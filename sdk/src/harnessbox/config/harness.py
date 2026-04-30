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
    cli_base_flags: tuple[str, ...] = ()
    cli_oneshot_flags: tuple[str, ...] = ()
    cli_interactive_flags: tuple[str, ...] = ()
    cli_prompt_flag: str = "-p"
    skip_permissions_flag: str | None = None
    cli_resume_flag: str | None = None
    default_template: str | None = None
    skills_dir: str | None = None
    plugin_flag: str | None = None
    skill_install_cmd: str | None = None
    cli_input_format_flag: str | None = None
    workspace_root: str = "/workspace"
    build_settings: Callable[[SecurityPolicy], dict[str, Any]] | None = None
    build_hook_script: Callable[[SecurityPolicy], str] | None = None

    @property
    def supports_persistent(self) -> bool:
        return self.cli_input_format_flag is not None

    def build_persistent_command(
        self,
        *,
        skip_permissions: bool,
        plugin_dirs: list[str] | None = None,
        session_id: str | None = None,
    ) -> str:
        """Build CLI command for persistent stdin/stdout stream-json mode."""
        parts = [self.cli_command]
        if skip_permissions and self.skip_permissions_flag:
            parts.append(self.skip_permissions_flag)
        parts.extend(self.cli_base_flags)
        if session_id and self.cli_resume_flag:
            parts.extend([self.cli_resume_flag, session_id])
        if self.cli_input_format_flag:
            parts.extend([self.cli_input_format_flag, "stream-json"])
        if plugin_dirs and self.plugin_flag:
            for d in plugin_dirs:
                parts.extend([self.plugin_flag, d])
        return " ".join(parts)

    def build_oneshot_command(
        self,
        prompt: str,
        *,
        skip_permissions: bool,
        session_id: str | None = None,
        plugin_dirs: list[str] | None = None,
    ) -> str:
        """Build the full CLI command for a one-shot prompt run."""
        parts = [self.cli_command]
        if skip_permissions and self.skip_permissions_flag:
            parts.append(self.skip_permissions_flag)
        parts.extend(self.cli_base_flags)
        if session_id and self.cli_resume_flag:
            parts.extend([self.cli_resume_flag, session_id])
        if plugin_dirs and self.plugin_flag:
            for d in plugin_dirs:
                parts.extend([self.plugin_flag, d])
        parts.extend(self.cli_oneshot_flags)
        parts.append(f"{self.cli_prompt_flag} {prompt}")
        return " ".join(parts)

    def build_interactive_command(
        self, *, skip_permissions: bool, plugin_dirs: list[str] | None = None
    ) -> str:
        """Build the full CLI command for interactive mode."""
        parts = [self.cli_command]
        if skip_permissions and self.skip_permissions_flag:
            parts.append(self.skip_permissions_flag)
        parts.extend(self.cli_base_flags)
        if plugin_dirs and self.plugin_flag:
            for d in plugin_dirs:
                parts.extend([self.plugin_flag, d])
        parts.extend(self.cli_interactive_flags)
        return " ".join(parts)


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


def _claude_code_build_hook(policy: SecurityPolicy) -> str:
    from harnessbox.security.hooks import build_guard_script

    return build_guard_script(policy)


register_harness_type(
    HarnessTypeConfig(
        name="claude-code",
        config_dir=".claude",
        settings_file=".claude/settings.json",
        hooks_dir=".claude/hooks",
        system_prompt_file="CLAUDE.md",
        default_dirs=("/workspace/user_input", "/workspace/output"),
        cli_command="claude",
        cli_base_flags=(
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
        ),
        cli_oneshot_flags=(),
        cli_interactive_flags=(),
        cli_prompt_flag="-p",
        skip_permissions_flag="--dangerously-skip-permissions",
        cli_resume_flag="--resume",
        default_template="claude",
        skills_dir=".claude/skills",
        plugin_flag="--plugin-dir",
        skill_install_cmd="npx skills add",
        cli_input_format_flag="--input-format",
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
        cli_base_flags=("--model", "o4-mini"),
        cli_oneshot_flags=("-q",),
        cli_prompt_flag="",
        skip_permissions_flag="--full-auto",
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
        cli_base_flags=(),
        cli_prompt_flag="-p",
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
        cli_base_flags=(),
        cli_prompt_flag="-p",
    )
)
