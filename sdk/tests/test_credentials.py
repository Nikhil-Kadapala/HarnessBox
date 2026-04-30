"""Tests for harnessbox.credentials — host credential detection."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from harnessbox.credentials import (
    CredentialProbe,
    CredentialStatus,
    detect_credentials,
)


class TestProbeEnvVars:
    def test_present_env_var(self) -> None:
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-test123"}):
            status = detect_credentials()
        probe = next(p for p in status.probes if p.name == "ANTHROPIC_API_KEY")
        assert probe.available is True

    def test_missing_env_var(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            status = detect_credentials()
        probe = next(p for p in status.probes if p.name == "ANTHROPIC_API_KEY")
        assert probe.available is False

    def test_empty_env_var(self) -> None:
        with patch.dict("os.environ", {"E2B_API_KEY": "  "}):
            status = detect_credentials()
        probe = next(p for p in status.probes if p.name == "E2B_API_KEY")
        assert probe.available is False

    def test_all_env_vars_probed(self) -> None:
        status = detect_credentials()
        env_names = {p.name for p in status.probes if p.name.isupper()}
        expected = {
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "E2B_API_KEY",
            "GITHUB_TOKEN",
            "GOOGLE_API_KEY",
            "GEMINI_API_KEY",
        }
        assert expected.issubset(env_names)


class TestProbeGhCli:
    def test_gh_cli_present(self, tmp_path: Path) -> None:
        hosts = tmp_path / ".config" / "gh" / "hosts.yml"
        hosts.parent.mkdir(parents=True)
        hosts.write_text("github.com:\n  user: testuser\n")
        with patch("harnessbox.credentials.Path.home", return_value=tmp_path):
            status = detect_credentials()
        probe = next(p for p in status.probes if p.name == "gh_cli")
        assert probe.available is True

    def test_gh_cli_missing(self, tmp_path: Path) -> None:
        with patch("harnessbox.credentials.Path.home", return_value=tmp_path):
            status = detect_credentials()
        probe = next(p for p in status.probes if p.name == "gh_cli")
        assert probe.available is False

    def test_gh_cli_empty_file(self, tmp_path: Path) -> None:
        hosts = tmp_path / ".config" / "gh" / "hosts.yml"
        hosts.parent.mkdir(parents=True)
        hosts.write_text("")
        with patch("harnessbox.credentials.Path.home", return_value=tmp_path):
            status = detect_credentials()
        probe = next(p for p in status.probes if p.name == "gh_cli")
        assert probe.available is False


class TestProbeE2bCli:
    def test_e2b_with_access_token(self, tmp_path: Path) -> None:
        config = tmp_path / ".e2b" / "config.json"
        config.parent.mkdir(parents=True)
        config.write_text('{"accessToken": "sk_e2b_test", "teamApiKey": ""}')
        with patch("harnessbox.credentials.Path.home", return_value=tmp_path):
            status = detect_credentials()
        probe = next(p for p in status.probes if p.name == "e2b_cli")
        assert probe.available is True

    def test_e2b_with_team_api_key(self, tmp_path: Path) -> None:
        config = tmp_path / ".e2b" / "config.json"
        config.parent.mkdir(parents=True)
        config.write_text('{"teamApiKey": "e2b_teamkey123"}')
        with patch("harnessbox.credentials.Path.home", return_value=tmp_path):
            status = detect_credentials()
        probe = next(p for p in status.probes if p.name == "e2b_cli")
        assert probe.available is True

    def test_e2b_missing(self, tmp_path: Path) -> None:
        with patch("harnessbox.credentials.Path.home", return_value=tmp_path):
            status = detect_credentials()
        probe = next(p for p in status.probes if p.name == "e2b_cli")
        assert probe.available is False

    def test_e2b_invalid_json(self, tmp_path: Path) -> None:
        config = tmp_path / ".e2b" / "config.json"
        config.parent.mkdir(parents=True)
        config.write_text("not json")
        with patch("harnessbox.credentials.Path.home", return_value=tmp_path):
            status = detect_credentials()
        probe = next(p for p in status.probes if p.name == "e2b_cli")
        assert probe.available is False


class TestProbeClaudeCode:
    def test_claude_dir_exists(self, tmp_path: Path) -> None:
        (tmp_path / ".claude").mkdir()
        with patch("harnessbox.credentials.Path.home", return_value=tmp_path):
            status = detect_credentials()
        probe = next(p for p in status.probes if p.name == "claude_code")
        assert probe.available is True

    def test_claude_dir_missing(self, tmp_path: Path) -> None:
        with patch("harnessbox.credentials.Path.home", return_value=tmp_path):
            status = detect_credentials()
        probe = next(p for p in status.probes if p.name == "claude_code")
        assert probe.available is False


class TestDetectCredentials:
    def test_returns_credential_status(self) -> None:
        status = detect_credentials()
        assert isinstance(status, CredentialStatus)
        assert isinstance(status.timestamp, str)
        assert len(status.probes) > 0

    def test_probes_are_boolean_only(self) -> None:
        status = detect_credentials()
        for probe in status.probes:
            assert isinstance(probe, CredentialProbe)
            assert isinstance(probe.name, str)
            assert isinstance(probe.available, bool)
            assert not hasattr(probe, "value")
            assert not hasattr(probe, "masked_value")
            assert not hasattr(probe, "location")

    def test_never_raises(self, tmp_path: Path) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("harnessbox.credentials.Path.home", return_value=tmp_path),
        ):
            status = detect_credentials()
        assert isinstance(status, CredentialStatus)
