"""Tests for harnessbox._setup — manifest builder."""

from __future__ import annotations

import json

from harnessbox._setup import SandboxManifest, build_manifest
from harnessbox.harness import get_harness_type
from harnessbox.security import SecurityPolicy


class TestSandboxManifest:
    def test_defaults(self):
        m = SandboxManifest()
        assert m.dirs == []
        assert m.files == {}
        assert m.env_vars == {}


class TestBuildManifestClaudeCode:
    def _claude_config(self):
        return get_harness_type("claude-code")

    def test_includes_default_dirs(self):
        m = build_manifest(
            self._claude_config(), None, "/workspace", None, None, None, None
        )
        assert "/workspace/user_input" in m.dirs
        assert "/workspace/output" in m.dirs

    def test_includes_config_dir(self):
        m = build_manifest(
            self._claude_config(), None, "/workspace", None, None, None, None
        )
        assert "/workspace/.claude" in m.dirs

    def test_includes_hooks_dir(self):
        m = build_manifest(
            self._claude_config(), None, "/workspace", None, None, None, None
        )
        assert "/workspace/.claude/hooks" in m.dirs

    def test_security_settings_when_policy_provided(self):
        policy = SecurityPolicy(denied_tools=["WebFetch"], deny_network=True)
        m = build_manifest(
            self._claude_config(), policy, "/workspace", None, None, None, None
        )
        assert "/workspace/.claude/settings.json" in m.files
        settings = json.loads(m.files["/workspace/.claude/settings.json"])
        assert "permissions" in settings

    def test_hook_script_when_policy_provided(self):
        policy = SecurityPolicy()
        m = build_manifest(
            self._claude_config(), policy, "/workspace", None, None, None, None
        )
        assert "/workspace/.claude/hooks/guard_bash.py" in m.files

    def test_no_security_files_when_no_policy(self):
        m = build_manifest(
            self._claude_config(), None, "/workspace", None, None, None, None
        )
        assert "/workspace/.claude/settings.json" not in m.files
        assert "/workspace/.claude/hooks/guard_bash.py" not in m.files

    def test_system_prompt(self):
        m = build_manifest(
            self._claude_config(), None, "/workspace", None, None, None, "You are helpful."
        )
        assert m.files["/workspace/CLAUDE.md"] == "You are helpful."

    def test_no_system_prompt(self):
        m = build_manifest(
            self._claude_config(), None, "/workspace", None, None, None, None
        )
        assert "/workspace/CLAUDE.md" not in m.files

    def test_user_dirs_merged(self):
        m = build_manifest(
            self._claude_config(),
            None,
            "/workspace",
            None,
            ["/workspace/custom", "/workspace/user_input"],
            None,
            None,
        )
        assert "/workspace/custom" in m.dirs
        assert m.dirs.count("/workspace/user_input") == 1

    def test_user_files_override_generated(self):
        policy = SecurityPolicy()
        custom_settings = '{"custom": true}'
        m = build_manifest(
            self._claude_config(),
            policy,
            "/workspace",
            None,
            None,
            {"/workspace/.claude/settings.json": custom_settings},
            None,
        )
        assert m.files["/workspace/.claude/settings.json"] == custom_settings

    def test_user_files_create_parent_dirs(self):
        m = build_manifest(
            self._claude_config(),
            None,
            "/workspace",
            None,
            None,
            {"/workspace/deep/nested/file.txt": "content"},
            None,
        )
        assert "/workspace/deep/nested" in m.dirs

    def test_env_vars(self):
        m = build_manifest(
            self._claude_config(),
            None,
            "/workspace",
            {"FOO": "bar", "BAZ": "1"},
            None,
            None,
            None,
        )
        assert m.env_vars == {"FOO": "bar", "BAZ": "1"}

    def test_no_env_vars(self):
        m = build_manifest(
            self._claude_config(), None, "/workspace", None, None, None, None
        )
        assert m.env_vars == {}


class TestBuildManifestCodex:
    def _codex_config(self):
        return get_harness_type("codex")

    def test_no_settings_file_when_policy_provided(self):
        policy = SecurityPolicy(denied_tools=["WebFetch"])
        m = build_manifest(
            self._codex_config(), policy, "/workspace", None, None, None, None
        )
        assert not any("settings.json" in p for p in m.files)

    def test_no_hooks_dir(self):
        m = build_manifest(
            self._codex_config(), None, "/workspace", None, None, None, None
        )
        assert not any("hooks" in d for d in m.dirs)

    def test_system_prompt_uses_agents_md(self):
        m = build_manifest(
            self._codex_config(), None, "/workspace", None, None, None, "Be helpful."
        )
        assert m.files["/workspace/AGENTS.md"] == "Be helpful."
