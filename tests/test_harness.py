"""Tests for harnessbox.harness — harness type registry."""

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
        assert "gemini-cli" in types
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
            cli_oneshot_template="test-cli -p {prompt}",
            cli_interactive_template="test-cli",
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

    def test_oneshot_template_has_prompt_placeholder(self):
        config = get_harness_type("claude-code")
        assert "{prompt}" in config.cli_oneshot_template

    def test_oneshot_template_has_skip_permissions(self):
        config = get_harness_type("claude-code")
        assert "--dangerously-skip-permissions" in config.cli_oneshot_template

    def test_oneshot_template_has_stream_json(self):
        config = get_harness_type("claude-code")
        assert "stream-json" in config.cli_oneshot_template

    def test_interactive_template(self):
        config = get_harness_type("claude-code")
        assert "--dangerously-skip-permissions" in config.cli_interactive_template
        assert " -p " not in config.cli_interactive_template

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
        script = config.build_hook_script()
        assert isinstance(script, str)
        assert len(script) > 100
        compile(script, "<guard>", "exec")


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


class TestGeminiCliConfig:
    def test_system_prompt_file(self):
        config = get_harness_type("gemini-cli")
        assert config.system_prompt_file == "GEMINI.md"

    def test_cli_command(self):
        config = get_harness_type("gemini-cli")
        assert config.cli_command == "gemini"


class TestOpenCodeConfig:
    def test_system_prompt_file(self):
        config = get_harness_type("opencode")
        assert config.system_prompt_file == "AGENTS.md"

    def test_config_dir(self):
        config = get_harness_type("opencode")
        assert config.config_dir == ".opencode"
