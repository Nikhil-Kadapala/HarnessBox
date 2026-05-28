"""Tests for harnessbox.security — SecurityPolicy, resolve, and settings builder."""

import json

import pytest

from harnessbox.security.policy import SecurityPolicy, build_settings, resolve_credential_guards


class TestSecurityPolicy:
    def test_default_construction(self) -> None:
        policy = SecurityPolicy()
        assert policy.denied_tools == []
        assert policy.denied_bash_patterns == []
        assert policy.deny_network is False
        assert policy.credential_guards is True

    def test_frozen(self) -> None:
        policy = SecurityPolicy()
        with pytest.raises(AttributeError):
            policy.deny_network = True  # type: ignore[misc]


class TestResolveCredentialGuards:
    def test_default_returns_all(self) -> None:
        names = resolve_credential_guards(SecurityPolicy())
        assert names is not None
        assert len(names) == 10

    def test_false_returns_none(self) -> None:
        assert resolve_credential_guards(SecurityPolicy(credential_guards=False)) is None

    def test_true_returns_all(self) -> None:
        names = resolve_credential_guards(SecurityPolicy(credential_guards=True))
        assert names is not None
        assert len(names) == 10

    def test_all_string_returns_all(self) -> None:
        names = resolve_credential_guards(SecurityPolicy(credential_guards="all"))
        assert names is not None
        assert len(names) == 10

    def test_single_string(self) -> None:
        names = resolve_credential_guards(SecurityPolicy(credential_guards="aws"))
        assert names == frozenset({"aws"})

    def test_list_of_names(self) -> None:
        names = resolve_credential_guards(SecurityPolicy(credential_guards=["aws", "gcp"]))
        assert names == frozenset({"aws", "gcp"})

    def test_unknown_string_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown credential guard set"):
            resolve_credential_guards(SecurityPolicy(credential_guards="nonexistent"))

    def test_unknown_list_entry_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown credential guard set"):
            resolve_credential_guards(SecurityPolicy(credential_guards=["aws", "bad"]))


class TestBuildSettings:
    def test_json_serializable(self) -> None:
        settings = build_settings(SecurityPolicy())
        roundtripped = json.loads(json.dumps(settings))
        assert roundtripped == settings

    def test_includes_credential_guards_by_default(self) -> None:
        settings = build_settings(SecurityPolicy())
        deny = settings["permissions"]["deny"]
        assert "env" in deny["Bash"]
        assert ".env" in deny["Read"]

    def test_omits_credential_guards_when_disabled(self) -> None:
        settings = build_settings(SecurityPolicy(credential_guards=False))
        deny = settings["permissions"]["deny"]
        assert "env" not in deny["Bash"]
        assert ".env" not in deny["Read"]

    def test_selective_guards_aws_only(self) -> None:
        settings = build_settings(SecurityPolicy(credential_guards=["aws"]))
        deny = settings["permissions"]["deny"]
        assert any("169.254.169.254" in p for p in deny["Bash"])
        assert "~/.aws/credentials" in deny["Read"]
        assert not any("metadata.google.internal" in p for p in deny["Bash"])

    def test_selective_guards_gcp_only(self) -> None:
        settings = build_settings(SecurityPolicy(credential_guards=["gcp"]))
        deny = settings["permissions"]["deny"]
        assert any("metadata.google.internal" in p for p in deny["Bash"])
        assert not any("aws" in p.lower() for p in deny["Read"] if "aws" in p.lower())

    def test_extra_bash_guards(self) -> None:
        settings = build_settings(
            SecurityPolicy(credential_guards=["aws"], extra_bash_guards=["my-custom-pattern"])
        )
        assert "my-custom-pattern" in settings["permissions"]["deny"]["Bash"]

    def test_extra_read_guards(self) -> None:
        settings = build_settings(
            SecurityPolicy(credential_guards=["aws"], extra_read_guards=["~/.my/secret"])
        )
        assert "~/.my/secret" in settings["permissions"]["deny"]["Read"]

    def test_denied_tools(self) -> None:
        settings = build_settings(SecurityPolicy(denied_tools=["WebFetch", "Agent"]))
        deny = settings["permissions"]["deny"]
        assert deny["WebFetch"] == ["*"]
        assert deny["Agent"] == ["*"]

    def test_deny_network_adds_web_tools(self) -> None:
        settings = build_settings(SecurityPolicy(deny_network=True))
        deny = settings["permissions"]["deny"]
        assert deny["WebFetch"] == ["*"]
        assert deny["WebSearch"] == ["*"]

    def test_custom_bash_patterns(self) -> None:
        settings = build_settings(SecurityPolicy(denied_bash_patterns=["rm -rf /"]))
        assert "rm -rf /" in settings["permissions"]["deny"]["Bash"]

    def test_hooks_config_present(self) -> None:
        settings = build_settings(SecurityPolicy())
        hooks = settings["hooks"]
        assert "PreToolUse" in hooks
        assert hooks["PreToolUse"][0]["matcher"] == "Bash"
        assert "guard_bash.py" in hooks["PreToolUse"][0]["hooks"][0]["command"]
