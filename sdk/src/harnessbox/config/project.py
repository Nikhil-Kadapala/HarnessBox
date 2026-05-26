"""Project config — loads .harnessbox.toml from target repositories."""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass, field
from typing import Any

from harnessbox.config.harness import HarnessTypeConfig, register_harness_type

_log = logging.getLogger("harnessbox.project")

_FORBIDDEN_SECTIONS = frozenset({"security", "provider", "secrets"})


class ProjectConfigError(ValueError):
    """Raised when .harnessbox.toml has invalid content."""


@dataclass(frozen=True)
class WorkspacePreset:
    """Workspace setup values from [workspace] in .harnessbox.toml."""

    setup_script: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)
    extra_dirs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AgentPreference:
    """Agent selection hints from [agent] in .harnessbox.toml."""

    prefer: str | None = None
    model: str | None = None


@dataclass(frozen=True)
class CustomAgentSpec:
    """Typed representation of a [[agents]] entry."""

    name: str
    cli_command: str
    config_dir: str = ""
    system_prompt_file: str = "AGENTS.md"
    default_dirs: tuple[str, ...] = ("/workspace",)
    cli_base_flags: tuple[str, ...] = ()
    cli_oneshot_flags: tuple[str, ...] = ()
    cli_interactive_flags: tuple[str, ...] = ()
    cli_prompt_flag: str = "-p"
    skip_permissions_flag: str | None = None
    cli_resume_flag: str | None = None
    cli_input_format_flag: str | None = None
    settings_file: str | None = None
    hooks_dir: str | None = None
    workspace_root: str = "/workspace"


@dataclass(frozen=True)
class ProjectConfig:
    """Parsed and validated .harnessbox.toml content."""

    workspace: WorkspacePreset = field(default_factory=WorkspacePreset)
    agent: AgentPreference = field(default_factory=AgentPreference)
    custom_agents: list[CustomAgentSpec] = field(default_factory=list)


def load_project_config(toml_content: str) -> ProjectConfig:
    """Parse TOML string into a validated ProjectConfig.

    Raises ProjectConfigError for type mismatches or malformed content.
    Unknown keys are silently ignored (forward compat).
    Forbidden sections (security, provider, secrets) are logged and ignored.
    """
    try:
        data = tomllib.loads(toml_content)
    except tomllib.TOMLDecodeError as e:
        raise ProjectConfigError(f"Invalid TOML: {e}") from e

    for key in _FORBIDDEN_SECTIONS & data.keys():
        _log.warning("Ignoring forbidden section [%s] in .harnessbox.toml", key)

    data = {k: v for k, v in data.items() if k not in _FORBIDDEN_SECTIONS}

    workspace = _parse_workspace(data.get("workspace", {}))
    agent = _parse_agent(data.get("agent", {}))
    custom_agents = _parse_agents_list(data.get("agents", []))

    return ProjectConfig(workspace=workspace, agent=agent, custom_agents=custom_agents)


def _parse_workspace(raw: Any) -> WorkspacePreset:
    if not isinstance(raw, dict):
        raise ProjectConfigError("[workspace] must be a table, got " + type(raw).__name__)

    setup_script = raw.get("setup_script")
    if setup_script is not None and not isinstance(setup_script, str):
        raise ProjectConfigError("[workspace].setup_script must be a string")

    env = raw.get("env", {})
    if not isinstance(env, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in env.items()
    ):
        raise ProjectConfigError("[workspace].env must be a table of string key-value pairs")

    files = raw.get("files", {})
    if not isinstance(files, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in files.items()
    ):
        raise ProjectConfigError("[workspace].files must be a table of string key-value pairs")

    extra_dirs = raw.get("dirs", {}).get("extra", []) if isinstance(raw.get("dirs"), dict) else []
    if not isinstance(extra_dirs, list) or not all(isinstance(d, str) for d in extra_dirs):
        raise ProjectConfigError("[workspace].dirs.extra must be a list of strings")

    return WorkspacePreset(
        setup_script=setup_script,
        env=dict(env),
        files=dict(files),
        extra_dirs=list(extra_dirs),
    )


def _parse_agent(raw: Any) -> AgentPreference:
    if not isinstance(raw, dict):
        raise ProjectConfigError("[agent] must be a table, got " + type(raw).__name__)

    prefer = raw.get("prefer")
    if prefer is not None and not isinstance(prefer, str):
        raise ProjectConfigError("[agent].prefer must be a string")

    model = raw.get("model")
    if model is not None and not isinstance(model, str):
        raise ProjectConfigError("[agent].model must be a string")

    return AgentPreference(prefer=prefer, model=model)


def _parse_agents_list(raw: Any) -> list[CustomAgentSpec]:
    if not isinstance(raw, list):
        raise ProjectConfigError("[[agents]] must be an array of tables")

    specs: list[CustomAgentSpec] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ProjectConfigError(f"[[agents]][{i}] must be a table")
        specs.append(_agent_spec_from_dict(entry, index=i))
    return specs


def _agent_spec_from_dict(data: dict[str, Any], index: int) -> CustomAgentSpec:
    name = data.get("name")
    if not isinstance(name, str) or not name:
        raise ProjectConfigError(
            f"[[agents]][{index}].name is required and must be a non-empty string"
        )

    cli_command = data.get("cli_command")
    if not isinstance(cli_command, str) or not cli_command:
        raise ProjectConfigError(
            f"[[agents]][{index}].cli_command is required and must be a non-empty string"
        )

    def _str_or_none(key: str) -> str | None:
        val = data.get(key)
        if val is None:
            return None
        if not isinstance(val, str):
            raise ProjectConfigError(f"[[agents]][{index}].{key} must be a string")
        return val

    def _tuple_of_str(key: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
        val = data.get(key)
        if val is None:
            return default
        if not isinstance(val, list) or not all(isinstance(s, str) for s in val):
            raise ProjectConfigError(f"[[agents]][{index}].{key} must be a list of strings")
        return tuple(val)

    return CustomAgentSpec(
        name=name,
        cli_command=cli_command,
        config_dir=data.get("config_dir", "") if isinstance(data.get("config_dir"), str) else "",
        system_prompt_file=_str_or_none("system_prompt_file") or "AGENTS.md",
        default_dirs=_tuple_of_str("default_dirs", ("/workspace",)),
        cli_base_flags=_tuple_of_str("cli_base_flags"),
        cli_oneshot_flags=_tuple_of_str("cli_oneshot_flags"),
        cli_interactive_flags=_tuple_of_str("cli_interactive_flags"),
        cli_prompt_flag=_str_or_none("cli_prompt_flag") or "-p",
        skip_permissions_flag=_str_or_none("skip_permissions_flag"),
        cli_resume_flag=_str_or_none("cli_resume_flag"),
        cli_input_format_flag=_str_or_none("cli_input_format_flag"),
        settings_file=_str_or_none("settings_file"),
        hooks_dir=_str_or_none("hooks_dir"),
        workspace_root=data.get("workspace_root", "/workspace")
        if isinstance(data.get("workspace_root"), str)
        else "/workspace",
    )


def register_custom_agents(config: ProjectConfig) -> list[str]:
    """Register [[agents]] entries via existing register_harness_type().

    Returns the list of agent names that were registered.
    Raises ProjectConfigError if a custom agent name collides with a built-in.
    """
    from harnessbox.config.harness import _HARNESS_REGISTRY

    registered: list[str] = []
    for spec in config.custom_agents:
        if spec.name in _HARNESS_REGISTRY:
            raise ProjectConfigError(
                f"Custom agent {spec.name!r} conflicts with a built-in harness type. "
                "Use a different name."
            )
        harness_config = HarnessTypeConfig(
            name=spec.name,
            config_dir=spec.config_dir,
            settings_file=spec.settings_file,
            hooks_dir=spec.hooks_dir,
            system_prompt_file=spec.system_prompt_file,
            default_dirs=spec.default_dirs,
            cli_command=spec.cli_command,
            cli_base_flags=spec.cli_base_flags,
            cli_oneshot_flags=spec.cli_oneshot_flags,
            cli_interactive_flags=spec.cli_interactive_flags,
            cli_prompt_flag=spec.cli_prompt_flag,
            skip_permissions_flag=spec.skip_permissions_flag,
            cli_resume_flag=spec.cli_resume_flag,
            cli_input_format_flag=spec.cli_input_format_flag,
            workspace_root=spec.workspace_root,
        )
        register_harness_type(harness_config)
        registered.append(spec.name)
    return registered


def merge_preset_into_context(
    preset: WorkspacePreset,
    *,
    ctx_env_vars: dict[str, str],
    ctx_files: dict[str, str],
    ctx_dirs: list[str],
    ctx_setup_script: str | None,
) -> tuple[dict[str, str], dict[str, str], list[str], str | None]:
    """Merge workspace preset into SetupContext values.

    Returns (env_vars, files, dirs, setup_script).
    TOML provides defaults; SDK/ctx values override.
    Setup scripts are concatenated: TOML first, then SDK.
    """
    merged_env = dict(preset.env)
    merged_env.update(ctx_env_vars)

    merged_files: dict[str, str] = {}
    for key, val in preset.files.items():
        clean_key = key.lstrip("/")
        merged_files[clean_key] = val
    merged_files.update(ctx_files)

    merged_dirs = list(preset.extra_dirs)
    for d in ctx_dirs:
        if d not in merged_dirs:
            merged_dirs.append(d)

    merged_script: str | None
    if preset.setup_script and ctx_setup_script:
        merged_script = f"{preset.setup_script}\n{ctx_setup_script}"
    elif preset.setup_script:
        merged_script = preset.setup_script
    else:
        merged_script = ctx_setup_script

    return merged_env, merged_files, merged_dirs, merged_script
