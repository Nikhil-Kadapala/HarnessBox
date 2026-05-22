"""Tests for harnessbox.config.harness — harness type registry and command builders."""

from __future__ import annotations

import pytest

from harnessbox.config.harness import (
    _HARNESS_REGISTRY,
    HarnessTypeConfig,
    get_harness_type,
    list_harness_types,
    register_harness_type,
)
from harnessbox.security.policy import SecurityPolicy


class TestRegistry:
    def test_builtin_types_registered(self):
        types = list_harness_types()
        assert "claude-code" in types
        assert "codex" in types
        assert "opencode" in types

    def test_list_returns_sorted(self):
        types = list_harness_types()
        assert types == sorted(types)

    def test_get_unknown_raises_key_error(self):
        with pytest.raises(KeyError, match="Unknown harness type"):
            get_harness_type("nonexistent")

    def test_key_error_lists_registered(self):
        with pytest.raises(KeyError, match="claude-code"):
            get_harness_type("nonexistent")

    def test_register_custom_type(self):
        custom = HarnessTypeConfig(
            name="test-harness",
            config_dir=".test",
            settings_file=None,
            hooks_dir=None,
            system_prompt_file="TEST.md",
            default_dirs=("/workspace",),
            cli_command="test-cli",
            cli_prompt_flag="-p",
        )
        register_harness_type(custom)
        assert get_harness_type("test-harness") is custom
        del _HARNESS_REGISTRY["test-harness"]


class TestClaudeCodeConfig:
    def test_config_dir(self):
        config = get_harness_type("claude-code")
        assert config.config_dir == ".claude"

    def test_settings_file(self):
        config = get_harness_type("claude-code")
        assert config.settings_file == ".claude/settings.json"

    def test_hooks_dir(self):
        config = get_harness_type("claude-code")
        assert config.hooks_dir == ".claude/hooks"

    def test_system_prompt_file(self):
        config = get_harness_type("claude-code")
        assert config.system_prompt_file == "CLAUDE.md"

    def test_default_dirs(self):
        config = get_harness_type("claude-code")
        assert "/workspace/user_input" in config.default_dirs
        assert "/workspace/output" in config.default_dirs

    def test_cli_command(self):
        config = get_harness_type("claude-code")
        assert config.cli_command == "claude"

    def test_skip_permissions_flag(self):
        config = get_harness_type("claude-code")
        assert config.skip_permissions_flag == "--dangerously-skip-permissions"

    def test_base_flags_include_stream_json(self):
        config = get_harness_type("claude-code")
        assert "--output-format" in config.cli_base_flags
        assert "stream-json" in config.cli_base_flags

    def test_workspace_root(self):
        config = get_harness_type("claude-code")
        assert config.workspace_root == "/workspace"

    def test_build_settings_callable(self):
        config = get_harness_type("claude-code")
        assert config.build_settings is not None
        policy = SecurityPolicy(denied_tools=["WebFetch"], deny_network=True)
        result = config.build_settings(policy)
        assert "permissions" in result
        assert "deny" in result["permissions"]
        assert "WebFetch" in result["permissions"]["deny"]

    def test_build_hook_script_callable(self):
        config = get_harness_type("claude-code")
        assert config.build_hook_script is not None
        policy = SecurityPolicy()
        script = config.build_hook_script(policy)
        assert isinstance(script, str)
        assert len(script) > 100
        compile(script, "<guard>", "exec")


class TestCommandBuilders:
    def test_oneshot_with_skip_permissions(self):
        config = get_harness_type("claude-code")
        cmd = config.build_oneshot_command('"hello"', skip_permissions=True)
        assert "--dangerously-skip-permissions" in cmd
        assert "stream-json" in cmd
        assert "-p" in cmd
        assert '"hello"' in cmd

    def test_oneshot_without_skip_permissions(self):
        config = get_harness_type("claude-code")
        cmd = config.build_oneshot_command('"hello"', skip_permissions=False)
        assert "--dangerously-skip-permissions" not in cmd
        assert "stream-json" in cmd

    def test_interactive_with_skip_permissions(self):
        config = get_harness_type("claude-code")
        cmd = config.build_interactive_command(skip_permissions=True)
        assert "--dangerously-skip-permissions" in cmd
        parts = cmd.split()
        assert "-p" not in parts

    def test_interactive_without_skip_permissions(self):
        config = get_harness_type("claude-code")
        cmd = config.build_interactive_command(skip_permissions=False)
        assert "--dangerously-skip-permissions" not in cmd

    def test_codex_oneshot(self):
        config = get_harness_type("codex")
        cmd = config.build_oneshot_command('"fix bugs"', skip_permissions=True)
        assert "--full-auto" in cmd
        assert "--model" in cmd
        assert "o4-mini" in cmd
        assert "-q" in cmd

    def test_harness_without_skip_flag(self):
        config = get_harness_type("opencode")
        cmd = config.build_oneshot_command('"hello"', skip_permissions=True)
        assert "--dangerously-skip-permissions" not in cmd
        assert "opencode" in cmd


class TestCodexConfig:
    def test_system_prompt_file(self):
        config = get_harness_type("codex")
        assert config.system_prompt_file == "AGENTS.md"

    def test_no_build_settings(self):
        config = get_harness_type("codex")
        assert config.build_settings is None

    def test_no_hooks_dir(self):
        config = get_harness_type("codex")
        assert config.hooks_dir is None


class TestOpenCodeConfig:
    def test_system_prompt_file(self):
        config = get_harness_type("opencode")
        assert config.system_prompt_file == "AGENTS.md"

    def test_config_dir(self):
        config = get_harness_type("opencode")
        assert config.config_dir == ".opencode"


class TestBuildSessionCommand:
    def test_without_session_id(self) -> None:
        cfg = get_harness_type("claude-code")
        cmd = cfg.build_session_command(skip_permissions=True)
        assert "--resume" not in cmd
        assert "--input-format" in cmd
        assert "--dangerously-skip-permissions" in cmd

    def test_with_session_id_includes_resume_flag(self) -> None:
        cfg = get_harness_type("claude-code")
        cmd = cfg.build_session_command(skip_permissions=True, session_id="abc-123")
        assert "--resume abc-123" in cmd
        parts = cmd.split()
        resume_idx = parts.index("--resume")
        input_idx = parts.index("--input-format")
        assert resume_idx < input_idx

    def test_session_id_none_same_as_omitted(self) -> None:
        cfg = get_harness_type("claude-code")
        cmd_none = cfg.build_session_command(skip_permissions=True, session_id=None)
        cmd_omit = cfg.build_session_command(skip_permissions=True)
        assert cmd_none == cmd_omit
