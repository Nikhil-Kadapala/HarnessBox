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
    cli_input_format_flag: str | None = None
    workspace_root: str = "/workspace"
    build_settings: Callable[[SecurityPolicy], dict[str, Any]] | None = None
    build_hook_script: Callable[[SecurityPolicy], str] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HarnessTypeConfig:
        """Create a HarnessTypeConfig from a dictionary (e.g., parsed TOML).

        Lists are coerced to tuples for tuple-typed fields.
        Unknown keys are silently ignored. Callable fields (build_settings,
        build_hook_script) cannot be expressed in config and default to None.

        Raises ValueError for required fields that are missing or have wrong types.
        """

        def _to_tuple(val: Any, default: tuple[str, ...] = ()) -> tuple[str, ...]:
            if val is None:
                return default
            if isinstance(val, (list, tuple)):
                if not all(isinstance(s, str) for s in val):
                    raise ValueError(f"All elements must be strings, got: {val!r}")
                return tuple(val)
            return default

        name = data.get("name", "")
        if not isinstance(name, str):
            raise ValueError(f"'name' must be a string, got {type(name).__name__}")
        cli_command = data.get("cli_command", "")
        if not isinstance(cli_command, str):
            raise ValueError(f"'cli_command' must be a string, got {type(cli_command).__name__}")

        return cls(
            name=name,
            config_dir=data.get("config_dir", ""),
            settings_file=data.get("settings_file"),
            hooks_dir=data.get("hooks_dir"),
            system_prompt_file=data.get("system_prompt_file", "AGENTS.md"),
            default_dirs=_to_tuple(data.get("default_dirs"), ("/workspace",)),
            cli_command=cli_command,
            cli_base_flags=_to_tuple(data.get("cli_base_flags")),
            cli_oneshot_flags=_to_tuple(data.get("cli_oneshot_flags")),
            cli_interactive_flags=_to_tuple(data.get("cli_interactive_flags")),
            cli_prompt_flag=data.get("cli_prompt_flag", "-p"),
            skip_permissions_flag=data.get("skip_permissions_flag"),
            cli_resume_flag=data.get("cli_resume_flag"),
            default_template=data.get("default_template"),
            cli_input_format_flag=data.get("cli_input_format_flag"),
            workspace_root=data.get("workspace_root", "/workspace"),
        )

    @property
    def supports_persistent(self) -> bool:
        """Return whether this harness supports persistent stdin/stdout mode."""
        return self.cli_input_format_flag is not None

    def build_session_command(
        self,
        *,
        skip_permissions: bool,
        model: str | None = None,
        session_id: str | None = None,
    ) -> str:
        """Build the CLI command that starts a persistent agent session.

        The resulting process accepts prompts via stdin (JSON lines) and
        streams responses on stdout. It stays alive across multiple turns.
        """
        parts = [self.cli_command]
        if skip_permissions and self.skip_permissions_flag:
            parts.append(self.skip_permissions_flag)
        parts.extend(self.cli_base_flags)
        if model:
            parts.extend(["--model", model])
        if session_id and self.cli_resume_flag:
            parts.extend([self.cli_resume_flag, session_id])
        if self.cli_input_format_flag:
            parts.extend([self.cli_input_format_flag, "stream-json"])
        return " ".join(parts)

    def build_oneshot_command(
        self,
        prompt: str,
        *,
        skip_permissions: bool,
        model: str | None = None,
        session_id: str | None = None,
    ) -> str:
        """Build the full CLI command for a one-shot prompt run."""
        parts = [self.cli_command]
        if skip_permissions and self.skip_permissions_flag:
            parts.append(self.skip_permissions_flag)
        parts.extend(self.cli_base_flags)
        if model:
            parts.extend(["--model", model])
        if session_id and self.cli_resume_flag:
            parts.extend([self.cli_resume_flag, session_id])
        parts.extend(self.cli_oneshot_flags)
        parts.append(f"{self.cli_prompt_flag} {prompt}")
        return " ".join(parts)

    def build_interactive_command(
        self, *, skip_permissions: bool
    ) -> str:
        """Build the full CLI command for interactive mode."""
        parts = [self.cli_command]
        if skip_permissions and self.skip_permissions_flag:
            parts.append(self.skip_permissions_flag)
        parts.extend(self.cli_base_flags)
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
