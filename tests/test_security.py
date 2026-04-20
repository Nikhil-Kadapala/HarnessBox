"""Tests for harnessbox.security — SecurityPolicy and settings builder."""

import json

import pytest

from harnessbox.security.policy import SecurityPolicy, build_settings, credential_deny_rules


class TestSecurityPolicy:
    def test_default_construction(self) -> None:
        policy = SecurityPolicy()
        assert policy.denied_tools == []
        assert policy.denied_bash_patterns == []
        assert policy.deny_network is False
        assert policy.include_credential_guards is True

    def test_frozen(self) -> None:
        policy = SecurityPolicy()
        with pytest.raises(AttributeError):
            policy.deny_network = True  # type: ignore[misc]


class TestCredentialDenyRules:
    def test_returns_bash_and_read_keys(self) -> None:
        rules = credential_deny_rules()
        assert "Bash" in rules
        assert "Read" in rules

    def test_bash_rules_include_env_commands(self) -> None:
        rules = credential_deny_rules()
        assert "env" in rules["Bash"]
        assert "printenv" in rules["Bash"]

    def test_bash_rules_include_imds(self) -> None:
        rules = credential_deny_rules()
        imds_rules = [r for r in rules["Bash"] if "169.254" in r]
        assert len(imds_rules) >= 1

    def test_bash_rules_include_gcp_metadata(self) -> None:
        rules = credential_deny_rules()
        gcp_rules = [r for r in rules["Bash"] if "metadata.google" in r]
        assert len(gcp_rules) >= 1

    def test_read_rules_include_env_files(self) -> None:
        rules = credential_deny_rules()
        assert ".env" in rules["Read"]

    def test_read_rules_include_settings(self) -> None:
        rules = credential_deny_rules()
        assert ".claude/settings.local.json" in rules["Read"]

    def test_read_rules_include_aws_creds(self) -> None:
        rules = credential_deny_rules()
        assert "~/.aws/credentials" in rules["Read"]


class TestBuildSettings:
    def test_json_serializable(self) -> None:
        policy = SecurityPolicy()
        settings = build_settings(policy)
        roundtripped = json.loads(json.dumps(settings))
        assert roundtripped == settings

    def test_includes_credential_guards_by_default(self) -> None:
        policy = SecurityPolicy()
        settings = build_settings(policy)
        deny = settings["permissions"]["deny"]
        assert "env" in deny["Bash"]
        assert ".env" in deny["Read"]

    def test_omits_credential_guards_when_disabled(self) -> None:
        policy = SecurityPolicy(include_credential_guards=False)
        settings = build_settings(policy)
        deny = settings["permissions"]["deny"]
        assert "env" not in deny["Bash"]
        assert ".env" not in deny["Read"]

    def test_denied_tools(self) -> None:
        policy = SecurityPolicy(denied_tools=["WebFetch", "Agent"])
        settings = build_settings(policy)
        deny = settings["permissions"]["deny"]
        assert deny["WebFetch"] == ["*"]
        assert deny["Agent"] == ["*"]

    def test_deny_network_adds_web_tools(self) -> None:
        policy = SecurityPolicy(deny_network=True)
        settings = build_settings(policy)
        deny = settings["permissions"]["deny"]
        assert deny["WebFetch"] == ["*"]
        assert deny["WebSearch"] == ["*"]

    def test_deny_network_no_duplicates(self) -> None:
        policy = SecurityPolicy(denied_tools=["WebFetch"], deny_network=True)
        settings = build_settings(policy)
        deny = settings["permissions"]["deny"]
        assert deny["WebFetch"] == ["*"]
        assert deny["WebSearch"] == ["*"]

    def test_custom_bash_patterns(self) -> None:
        policy = SecurityPolicy(denied_bash_patterns=["rm -rf /"])
        settings = build_settings(policy)
        deny = settings["permissions"]["deny"]
        assert "rm -rf /" in deny["Bash"]

    def test_hooks_config_present(self) -> None:
        policy = SecurityPolicy()
        settings = build_settings(policy)
        hooks = settings["hooks"]
        assert "PreToolUse" in hooks
        pre_tool = hooks["PreToolUse"]
        assert len(pre_tool) == 1
        assert pre_tool[0]["matcher"] == "Bash"
        assert "guard_bash.py" in pre_tool[0]["hooks"][0]["command"]

    def test_full_analysis_policy(self) -> None:
        """Matches the planned AnalysisSandbox policy."""
        policy = SecurityPolicy(
            denied_tools=["WebFetch", "WebSearch", "Agent"],
            deny_network=True,
        )
        settings = build_settings(policy)
        deny = settings["permissions"]["deny"]
        assert deny["WebFetch"] == ["*"]
        assert deny["WebSearch"] == ["*"]
        assert deny["Agent"] == ["*"]
        assert "env" in deny["Bash"]

    def test_full_research_policy(self) -> None:
        """Matches the planned CompanyResearchSandbox policy."""
        policy = SecurityPolicy(
            denied_tools=["Agent", "WebFetch", "WebSearch"],
            deny_network=False,
        )
        settings = build_settings(policy)
        deny = settings["permissions"]["deny"]
        assert deny["Agent"] == ["*"]
        assert deny["WebFetch"] == ["*"]
        assert deny["WebSearch"] == ["*"]
