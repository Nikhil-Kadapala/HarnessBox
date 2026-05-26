"""Configuration subpackage — harness types, manifests, project config."""

from harnessbox.config.harness import (
    HarnessTypeConfig,
    get_harness_type,
    list_harness_types,
    register_harness_type,
)
from harnessbox.config.manifest import SandboxManifest, build_manifest
from harnessbox.config.project import (
    AgentPreference,
    CustomAgentSpec,
    ProjectConfig,
    ProjectConfigError,
    WorkspacePreset,
    load_project_config,
    merge_preset_into_context,
    register_custom_agents,
)

__all__ = [
    "AgentPreference",
    "CustomAgentSpec",
    "HarnessTypeConfig",
    "ProjectConfig",
    "ProjectConfigError",
    "SandboxManifest",
    "WorkspacePreset",
    "build_manifest",
    "get_harness_type",
    "list_harness_types",
    "load_project_config",
    "merge_preset_into_context",
    "register_custom_agents",
    "register_harness_type",
]
