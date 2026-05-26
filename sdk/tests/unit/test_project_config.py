"""Tests for harnessbox.config.project — project config loading and merging."""

from __future__ import annotations

import logging

import pytest

from harnessbox.config.harness import _HARNESS_REGISTRY, get_harness_type
from harnessbox.config.project import (
    CustomAgentSpec,
    ProjectConfig,
    ProjectConfigError,
    WorkspacePreset,
    load_project_config,
    merge_preset_into_context,
    register_custom_agents,
)


class TestLoadProjectConfig:
    def test_empty_toml(self):
        config = load_project_config("")
        assert config.workspace.setup_script is None
        assert config.workspace.env == {}
        assert config.workspace.files == {}
        assert config.agent.prefer is None
        assert config.custom_agents == []

    def test_workspace_section(self):
        toml = """
[workspace]
setup_script = "npm ci"

[workspace.env]
NODE_ENV = "development"
DEBUG = "true"

[workspace.files]
"CLAUDE.md" = "You are a helpful assistant."

[workspace.dirs]
extra = ["/workspace/tmp", "/workspace/cache"]
"""
        config = load_project_config(toml)
        assert config.workspace.setup_script == "npm ci"
        assert config.workspace.env == {"NODE_ENV": "development", "DEBUG": "true"}
        assert config.workspace.files == {"CLAUDE.md": "You are a helpful assistant."}
        assert config.workspace.extra_dirs == ["/workspace/tmp", "/workspace/cache"]

    def test_agent_section(self):
        toml = """
[agent]
prefer = "claude-code"
model = "sonnet"
"""
        config = load_project_config(toml)
        assert config.agent.prefer == "claude-code"
        assert config.agent.model == "sonnet"

    def test_custom_agents(self):
        toml = """
[[agents]]
name = "my-agent"
cli_command = "my-cli"
config_dir = ".myagent"
system_prompt_file = "MY_AGENT.md"
default_dirs = ["/workspace", "/workspace/output"]
cli_base_flags = ["--verbose", "--json"]
cli_prompt_flag = "--prompt"
"""
        config = load_project_config(toml)
        assert len(config.custom_agents) == 1
        agent = config.custom_agents[0]
        assert agent.name == "my-agent"
        assert agent.cli_command == "my-cli"
        assert agent.config_dir == ".myagent"
        assert agent.system_prompt_file == "MY_AGENT.md"
        assert agent.default_dirs == ("/workspace", "/workspace/output")
        assert agent.cli_base_flags == ("--verbose", "--json")
        assert agent.cli_prompt_flag == "--prompt"

    def test_multiple_custom_agents(self):
        toml = """
[[agents]]
name = "agent-a"
cli_command = "a-cli"

[[agents]]
name = "agent-b"
cli_command = "b-cli"
"""
        config = load_project_config(toml)
        assert len(config.custom_agents) == 2
        assert config.custom_agents[0].name == "agent-a"
        assert config.custom_agents[1].name == "agent-b"

    def test_agent_defaults(self):
        toml = """
[[agents]]
name = "minimal"
cli_command = "min-cli"
"""
        config = load_project_config(toml)
        agent = config.custom_agents[0]
        assert agent.config_dir == ""
        assert agent.system_prompt_file == "AGENTS.md"
        assert agent.default_dirs == ("/workspace",)
        assert agent.cli_base_flags == ()
        assert agent.cli_prompt_flag == "-p"
        assert agent.workspace_root == "/workspace"

    def test_forbidden_sections_ignored(self, caplog):
        toml = """
[security]
deny_network = true

[workspace]
setup_script = "echo hello"
"""
        with caplog.at_level(logging.WARNING, logger="harnessbox.project"):
            config = load_project_config(toml)
        assert config.workspace.setup_script == "echo hello"
        assert "Ignoring forbidden section [security]" in caplog.text

    def test_unknown_top_level_keys_ignored(self):
        toml = """
[unknown_future_section]
foo = "bar"

[workspace]
setup_script = "echo hi"
"""
        config = load_project_config(toml)
        assert config.workspace.setup_script == "echo hi"


class TestValidationErrors:
    def test_invalid_toml_syntax(self):
        with pytest.raises(ProjectConfigError, match="Invalid TOML"):
            load_project_config("[broken")

    def test_workspace_not_table(self):
        with pytest.raises(ProjectConfigError, match="must be a table"):
            load_project_config('workspace = "not a table"')

    def test_setup_script_wrong_type(self):
        with pytest.raises(ProjectConfigError, match="setup_script must be a string"):
            load_project_config("[workspace]\nsetup_script = 42")

    def test_env_wrong_type(self):
        with pytest.raises(ProjectConfigError, match="env must be a table"):
            load_project_config('[workspace]\nenv = "wrong"')

    def test_agent_missing_name(self):
        with pytest.raises(ProjectConfigError, match="name is required"):
            load_project_config('[[agents]]\ncli_command = "foo"')

    def test_agent_missing_cli_command(self):
        with pytest.raises(ProjectConfigError, match="cli_command is required"):
            load_project_config('[[agents]]\nname = "foo"')

    def test_agent_prefer_wrong_type(self):
        with pytest.raises(ProjectConfigError, match="prefer must be a string"):
            load_project_config("[agent]\nprefer = 42")


class TestRegisterCustomAgents:
    def test_register_new_agent(self):
        config = ProjectConfig(
            custom_agents=[
                CustomAgentSpec(
                    name="test-project-agent",
                    cli_command="test-proj",
                )
            ]
        )
        registered = register_custom_agents(config)
        assert registered == ["test-project-agent"]
        assert get_harness_type("test-project-agent").cli_command == "test-proj"
        del _HARNESS_REGISTRY["test-project-agent"]

    def test_conflict_with_builtin_raises(self):
        config = ProjectConfig(
            custom_agents=[
                CustomAgentSpec(
                    name="claude-code",
                    cli_command="fake",
                )
            ]
        )
        with pytest.raises(ProjectConfigError, match="conflicts with a built-in"):
            register_custom_agents(config)

    def test_empty_agents_noop(self):
        config = ProjectConfig(custom_agents=[])
        registered = register_custom_agents(config)
        assert registered == []


class TestMergePresetIntoContext:
    def test_sdk_env_overrides_toml(self):
        preset = WorkspacePreset(env={"A": "from-toml", "B": "from-toml"})
        env, _, _, _ = merge_preset_into_context(
            preset,
            ctx_env_vars={"A": "from-sdk"},
            ctx_files={},
            ctx_dirs=[],
            ctx_setup_script=None,
        )
        assert env == {"A": "from-sdk", "B": "from-toml"}

    def test_sdk_files_override_toml(self):
        preset = WorkspacePreset(files={"README.md": "toml", "other.txt": "toml"})
        _, files, _, _ = merge_preset_into_context(
            preset,
            ctx_env_vars={},
            ctx_files={"README.md": "sdk"},
            ctx_dirs=[],
            ctx_setup_script=None,
        )
        assert files["README.md"] == "sdk"
        assert files["other.txt"] == "toml"

    def test_dirs_merged_union(self):
        preset = WorkspacePreset(extra_dirs=["/workspace/a", "/workspace/b"])
        _, _, dirs, _ = merge_preset_into_context(
            preset,
            ctx_env_vars={},
            ctx_files={},
            ctx_dirs=["/workspace/b", "/workspace/c"],
            ctx_setup_script=None,
        )
        assert "/workspace/a" in dirs
        assert "/workspace/b" in dirs
        assert "/workspace/c" in dirs

    def test_setup_scripts_concatenated(self):
        preset = WorkspacePreset(setup_script="npm ci")
        _, _, _, script = merge_preset_into_context(
            preset,
            ctx_env_vars={},
            ctx_files={},
            ctx_dirs=[],
            ctx_setup_script="echo custom",
        )
        assert script == "npm ci\necho custom"

    def test_toml_only_setup_script(self):
        preset = WorkspacePreset(setup_script="npm ci")
        _, _, _, script = merge_preset_into_context(
            preset,
            ctx_env_vars={},
            ctx_files={},
            ctx_dirs=[],
            ctx_setup_script=None,
        )
        assert script == "npm ci"

    def test_sdk_only_setup_script(self):
        preset = WorkspacePreset()
        _, _, _, script = merge_preset_into_context(
            preset,
            ctx_env_vars={},
            ctx_files={},
            ctx_dirs=[],
            ctx_setup_script="echo sdk",
        )
        assert script == "echo sdk"

    def test_no_setup_scripts(self):
        preset = WorkspacePreset()
        _, _, _, script = merge_preset_into_context(
            preset,
            ctx_env_vars={},
            ctx_files={},
            ctx_dirs=[],
            ctx_setup_script=None,
        )
        assert script is None

    def test_file_paths_strip_leading_slash(self):
        preset = WorkspacePreset(files={"/leading/slash.txt": "content"})
        _, files, _, _ = merge_preset_into_context(
            preset,
            ctx_env_vars={},
            ctx_files={},
            ctx_dirs=[],
            ctx_setup_script=None,
        )
        assert "leading/slash.txt" in files


class TestHarnessTypeConfigFromDict:
    def test_minimal_dict(self):
        from harnessbox.config.harness import HarnessTypeConfig

        config = HarnessTypeConfig.from_dict({
            "name": "test-agent",
            "cli_command": "test-cli",
        })
        assert config.name == "test-agent"
        assert config.cli_command == "test-cli"
        assert config.default_dirs == ("/workspace",)
        assert config.build_settings is None
        assert config.build_hook_script is None

    def test_list_to_tuple_coercion(self):
        from harnessbox.config.harness import HarnessTypeConfig

        config = HarnessTypeConfig.from_dict({
            "name": "coerce-test",
            "cli_command": "ct",
            "default_dirs": ["/a", "/b", "/c"],
            "cli_base_flags": ["--verbose", "--json"],
        })
        assert isinstance(config.default_dirs, tuple)
        assert config.default_dirs == ("/a", "/b", "/c")
        assert config.cli_base_flags == ("--verbose", "--json")

    def test_unknown_keys_ignored(self):
        from harnessbox.config.harness import HarnessTypeConfig

        config = HarnessTypeConfig.from_dict({
            "name": "ignore-test",
            "cli_command": "ign",
            "future_key": "future_value",
        })
        assert config.name == "ignore-test"
