"""Tests for harnessbox.credentials — host credential detection."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from harnessbox.credentials import (
    CredentialProbe,
    CredentialStatus,
    build_gcloud_credential_files,
    build_gcloud_env_vars,
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


class TestProbeGcloudCli:
    def test_gcloud_adc_present(self, tmp_path: Path) -> None:
        adc = tmp_path / ".config" / "gcloud" / "application_default_credentials.json"
        adc.parent.mkdir(parents=True)
        adc.write_text('{"type": "authorized_user", "client_id": "x"}')
        with patch("harnessbox.credentials.Path.home", return_value=tmp_path):
            status = detect_credentials()
        probe = next(p for p in status.probes if p.name == "gcloud_cli")
        assert probe.available is True

    def test_gcloud_properties_with_account(self, tmp_path: Path) -> None:
        props = tmp_path / ".config" / "gcloud" / "properties"
        props.parent.mkdir(parents=True)
        props.write_text("[core]\naccount = user@example.com\nproject = my-proj\n")
        with patch("harnessbox.credentials.Path.home", return_value=tmp_path):
            status = detect_credentials()
        probe = next(p for p in status.probes if p.name == "gcloud_cli")
        assert probe.available is True

    def test_gcloud_config_default_with_account(self, tmp_path: Path) -> None:
        cfg = tmp_path / ".config" / "gcloud" / "configurations" / "config_default"
        cfg.parent.mkdir(parents=True)
        cfg.write_text("[core]\naccount = user@example.com\n")
        with patch("harnessbox.credentials.Path.home", return_value=tmp_path):
            status = detect_credentials()
        probe = next(p for p in status.probes if p.name == "gcloud_cli")
        assert probe.available is True

    def test_gcloud_missing(self, tmp_path: Path) -> None:
        with patch("harnessbox.credentials.Path.home", return_value=tmp_path):
            status = detect_credentials()
        probe = next(p for p in status.probes if p.name == "gcloud_cli")
        assert probe.available is False

    def test_gcloud_properties_without_account(self, tmp_path: Path) -> None:
        props = tmp_path / ".config" / "gcloud" / "properties"
        props.parent.mkdir(parents=True)
        props.write_text("[core]\nproject = my-proj\n")
        with patch("harnessbox.credentials.Path.home", return_value=tmp_path):
            status = detect_credentials()
        probe = next(p for p in status.probes if p.name == "gcloud_cli")
        assert probe.available is False

    def test_gcloud_custom_config_dir(self, tmp_path: Path) -> None:
        custom_dir = tmp_path / "custom-gcloud"
        custom_dir.mkdir()
        adc = custom_dir / "application_default_credentials.json"
        adc.write_text('{"type": "authorized_user"}')
        with patch.dict("os.environ", {"CLOUDSDK_CONFIG": str(custom_dir)}):
            status = detect_credentials()
        probe = next(p for p in status.probes if p.name == "gcloud_cli")
        assert probe.available is True

    def test_gcloud_in_probe_list(self) -> None:
        status = detect_credentials()
        names = {p.name for p in status.probes}
        assert "gcloud_cli" in names


class TestBuildGcloudEnvVars:
    def test_project_from_properties(self, tmp_path: Path) -> None:
        props = tmp_path / ".config" / "gcloud" / "properties"
        props.parent.mkdir(parents=True)
        props.write_text("[core]\nproject = my-proj\n")
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("harnessbox.credentials.Path.home", return_value=tmp_path),
        ):
            envs = build_gcloud_env_vars()
        assert envs["CLOUDSDK_CORE_PROJECT"] == "my-proj"

    def test_region_from_properties(self, tmp_path: Path) -> None:
        props = tmp_path / ".config" / "gcloud" / "properties"
        props.parent.mkdir(parents=True)
        props.write_text("[compute]\nregion = us-east1\n")
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("harnessbox.credentials.Path.home", return_value=tmp_path),
        ):
            envs = build_gcloud_env_vars()
        assert envs["CLOUDSDK_COMPUTE_REGION"] == "us-east1"

    def test_multi_section_parsing(self, tmp_path: Path) -> None:
        props = tmp_path / ".config" / "gcloud" / "properties"
        props.parent.mkdir(parents=True)
        props.write_text(
            "[core]\nproject = my-proj\naccount = u@ex.com\n\n"
            "[compute]\nregion = us-west2\nzone = us-west2-a\n"
        )
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("harnessbox.credentials.Path.home", return_value=tmp_path),
        ):
            envs = build_gcloud_env_vars()
        assert envs["CLOUDSDK_CORE_PROJECT"] == "my-proj"
        assert envs["CLOUDSDK_COMPUTE_REGION"] == "us-west2"

    def test_env_var_precedence(self, tmp_path: Path) -> None:
        props = tmp_path / ".config" / "gcloud" / "properties"
        props.parent.mkdir(parents=True)
        props.write_text("[core]\nproject = from-file\n")
        with (
            patch.dict("os.environ", {"CLOUDSDK_CORE_PROJECT": "from-env"}, clear=True),
            patch("harnessbox.credentials.Path.home", return_value=tmp_path),
        ):
            envs = build_gcloud_env_vars()
        assert envs["CLOUDSDK_CORE_PROJECT"] == "from-env"

    def test_no_credentials(self, tmp_path: Path) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("harnessbox.credentials.Path.home", return_value=tmp_path),
        ):
            envs = build_gcloud_env_vars()
        assert envs == {}


class TestBuildGcloudCredentialFiles:
    def test_adc_file_present(self, tmp_path: Path) -> None:
        adc_content = json.dumps({"type": "authorized_user", "client_id": "123"})
        adc = tmp_path / ".config" / "gcloud" / "application_default_credentials.json"
        adc.parent.mkdir(parents=True)
        adc.write_text(adc_content)
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("harnessbox.credentials.Path.home", return_value=tmp_path),
        ):
            files = build_gcloud_credential_files()
        expected_path = "/root/.config/gcloud/application_default_credentials.json"
        assert expected_path in files
        assert json.loads(files[expected_path]) == json.loads(adc_content)

    def test_adc_file_missing(self, tmp_path: Path) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("harnessbox.credentials.Path.home", return_value=tmp_path),
        ):
            files = build_gcloud_credential_files()
        assert files == {}

    def test_adc_invalid_json(self, tmp_path: Path) -> None:
        adc = tmp_path / ".config" / "gcloud" / "application_default_credentials.json"
        adc.parent.mkdir(parents=True)
        adc.write_text("not valid json {{{")
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("harnessbox.credentials.Path.home", return_value=tmp_path),
        ):
            files = build_gcloud_credential_files()
        assert files == {}

    def test_adc_custom_config_dir(self, tmp_path: Path) -> None:
        custom_dir = tmp_path / "custom-gcloud"
        custom_dir.mkdir()
        adc_content = json.dumps({"type": "service_account", "project_id": "proj"})
        (custom_dir / "application_default_credentials.json").write_text(adc_content)
        with patch.dict("os.environ", {"CLOUDSDK_CONFIG": str(custom_dir)}, clear=True):
            files = build_gcloud_credential_files()
        expected_path = "/root/.config/gcloud/application_default_credentials.json"
        assert expected_path in files
