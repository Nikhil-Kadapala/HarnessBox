"""Internal setup orchestration — computes file manifests for sandbox setup."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from harnessbox.config.harness import HarnessTypeConfig
from harnessbox.security.policy import SecurityPolicy


@dataclass
class SandboxManifest:
    """Complete specification of what to inject into a sandbox.

    Pure data — no I/O. The Sandbox class uses this to drive provider calls.
    """

    dirs: list[str] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)
    env_vars: dict[str, str] = field(default_factory=dict)


def build_manifest(
    harness_config: HarnessTypeConfig,
    security_policy: SecurityPolicy | None,
    workspace_root: str,
    env_vars: dict[str, str] | None,
    dirs: list[str] | None,
    files: dict[str, str] | None,
    system_prompt: str | None,
) -> SandboxManifest:
    """Compute the full file/directory manifest for sandbox setup.

    Merges harness-type defaults with user-provided overrides.
    User-specified files override any generated files at the same path.
    """
    all_dirs: list[str] = []
    all_files: dict[str, str] = {}

    # 1. Harness-type default directories
    for d in harness_config.default_dirs:
        if d not in all_dirs:
            all_dirs.append(d)

    # 2. Config directory + hooks directory
    config_dir_path = f"{workspace_root}/{harness_config.config_dir}"
    if config_dir_path not in all_dirs:
        all_dirs.append(config_dir_path)

    if harness_config.hooks_dir:
        hooks_dir_path = f"{workspace_root}/{harness_config.hooks_dir}"
        if hooks_dir_path not in all_dirs:
            all_dirs.append(hooks_dir_path)

    # 3. User-specified directories
    if dirs:
        for d in dirs:
            if d not in all_dirs:
                all_dirs.append(d)

    # 4. Security config files (harness-type-specific)
    if security_policy and harness_config.build_settings:
        settings_dict = harness_config.build_settings(security_policy)
        if harness_config.settings_file:
            settings_path = f"{workspace_root}/{harness_config.settings_file}"
            all_files[settings_path] = json.dumps(settings_dict, indent=2)

    if security_policy and harness_config.build_hook_script:
        hook_script = harness_config.build_hook_script()
        if harness_config.hooks_dir:
            hook_path = f"{workspace_root}/{harness_config.hooks_dir}/guard_bash.py"
            all_files[hook_path] = hook_script

    # 5. System prompt file
    if system_prompt:
        prompt_path = f"{workspace_root}/{harness_config.system_prompt_file}"
        all_files[prompt_path] = system_prompt

    # 6. User-specified files (override anything above)
    if files:
        for path, content in files.items():
            all_files[path] = content
            parent = path.rsplit("/", 1)[0]
            if parent and parent not in all_dirs:
                all_dirs.append(parent)

    # 7. Environment variables
    all_env_vars = dict(env_vars) if env_vars else {}

    return SandboxManifest(
        dirs=all_dirs,
        files=all_files,
        env_vars=all_env_vars,
    )
