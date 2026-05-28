"""Unit tests for _server/workspace_factory.py — credential injection and config construction."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from harnessbox._server.workspace_factory import (
    build_workspace_config,
    convert_ssh_to_https,
    extract_provider_key,
    get_git_auth_token,
    inject_host_credential_files,
    inject_host_env_vars,
)


class TestInjectHostEnvVars:
    def test_adds_claude_vars(self) -> None:
        env: dict[str, str] = {}
        with (
            patch(
                "harnessbox.credentials.build_claude_env_vars",
                return_value={"ANTHROPIC_API_KEY": "sk-test"},
            ),
            patch(
                "harnessbox.credentials.build_gcloud_env_vars",
                return_value={},
            ),
        ):
            inject_host_env_vars(env)
        assert env["ANTHROPIC_API_KEY"] == "sk-test"

    def test_does_not_overwrite_existing(self) -> None:
        env: dict[str, str] = {"ANTHROPIC_API_KEY": "user-provided"}
        with (
            patch(
                "harnessbox.credentials.build_claude_env_vars",
                return_value={"ANTHROPIC_API_KEY": "from-host"},
            ),
            patch(
                "harnessbox.credentials.build_gcloud_env_vars",
                return_value={},
            ),
        ):
            inject_host_env_vars(env)
        assert env["ANTHROPIC_API_KEY"] == "user-provided"

    def test_injects_from_host_env(self) -> None:
        env: dict[str, str] = {}
        with (
            patch(
                "harnessbox.credentials.build_claude_env_vars",
                return_value={},
            ),
            patch(
                "harnessbox.credentials.build_gcloud_env_vars",
                return_value={},
            ),
            patch.dict("os.environ", {"OPENAI_API_KEY": "oai-key"}, clear=False),
        ):
            inject_host_env_vars(env)
        assert env["OPENAI_API_KEY"] == "oai-key"


class TestInjectHostCredentialFiles:
    def test_returns_gcloud_adc(self) -> None:
        expected = {"/root/.config/gcloud/application_default_credentials.json": "/tmp/adc.json"}
        with patch(
            "harnessbox.credentials.build_gcloud_credential_files",
            return_value=expected,
        ):
            result = inject_host_credential_files()
        assert result == expected


class TestGetGitAuthToken:
    def test_from_env(self) -> None:
        with patch.dict("os.environ", {"GITHUB_TOKEN": "gh-token-123"}, clear=False):
            assert get_git_auth_token() == "gh-token-123"

    def test_from_gh_cli(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "gh-cli-token\n"
        with (
            patch.dict("os.environ", {"GITHUB_TOKEN": ""}, clear=False),
            patch("subprocess.run", return_value=mock_result),
        ):
            assert get_git_auth_token() == "gh-cli-token"

    def test_returns_none_when_unavailable(self) -> None:
        with (
            patch.dict("os.environ", {"GITHUB_TOKEN": ""}, clear=False),
            patch("subprocess.run", side_effect=FileNotFoundError),
        ):
            assert get_git_auth_token() is None


class TestExtractProviderKey:
    def test_from_request_env_vars(self) -> None:
        env = {"E2B_API_KEY": "from-request"}
        assert extract_provider_key("e2b", env) == "from-request"

    def test_from_host_env(self) -> None:
        env: dict[str, str] = {}
        with patch.dict("os.environ", {"E2B_API_KEY": "from-host"}, clear=False):
            assert extract_provider_key("e2b", env) == "from-host"

    def test_from_e2b_config_file(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text('{"teamApiKey": "from-config"}')
        env: dict[str, str] = {}
        with (
            patch.dict("os.environ", {"E2B_API_KEY": ""}, clear=False),
            patch("pathlib.Path.home", return_value=tmp_path / ".."),
        ):
            # The function looks at Path.home() / ".e2b" / "config.json"
            e2b_dir = tmp_path / ".." / ".e2b"
            e2b_dir.mkdir(parents=True, exist_ok=True)
            (e2b_dir / "config.json").write_text('{"teamApiKey": "from-config"}')
            assert extract_provider_key("e2b", env) == "from-config"

    def test_returns_none_for_unknown_provider(self) -> None:
        assert extract_provider_key("unknown-provider", {}) is None


class TestConvertSshToHttps:
    def test_github_ssh(self) -> None:
        assert (
            convert_ssh_to_https("git@github.com:user/repo.git")
            == "https://github.com/user/repo.git"
        )

    def test_gitlab_ssh(self) -> None:
        assert (
            convert_ssh_to_https("git@gitlab.com:org/project.git")
            == "https://gitlab.com/org/project.git"
        )

    def test_https_passthrough(self) -> None:
        url = "https://github.com/user/repo.git"
        assert convert_ssh_to_https(url) == url

    def test_http_passthrough(self) -> None:
        url = "http://gitlab.internal/group/repo.git"
        assert convert_ssh_to_https(url) == url


class TestBuildWorkspaceConfig:
    def _make_request(self, **overrides):
        from harnessbox.server import CreateSessionRequest

        defaults = {
            "provider": "e2b",
            "sandbox_timeout": 1800,
            "session_timeout": 900,
        }
        defaults.update(overrides)
        return CreateSessionRequest(**defaults)

    def test_without_workspace(self) -> None:
        req = self._make_request()
        with (
            patch("harnessbox._server.workspace_factory.inject_host_env_vars"),
            patch(
                "harnessbox._server.workspace_factory.inject_host_credential_files",
                return_value={},
            ),
            patch(
                "harnessbox._server.workspace_factory.extract_provider_key",
                return_value="test-key",
            ),
        ):
            config = build_workspace_config(req)
        assert config.provider == "e2b"
        assert config.api_key == "test-key"
        assert config.workspace is None

    def test_with_workspace(self) -> None:
        from harnessbox.server import WorkspaceRequest

        req = self._make_request(
            workspace=WorkspaceRequest(remote="https://github.com/o/r.git", branch="main")
        )
        with (
            patch("harnessbox._server.workspace_factory.inject_host_env_vars"),
            patch(
                "harnessbox._server.workspace_factory.inject_host_credential_files",
                return_value={},
            ),
            patch(
                "harnessbox._server.workspace_factory.extract_provider_key",
                return_value="k",
            ),
            patch(
                "harnessbox._server.workspace_factory.get_git_auth_token",
                return_value="gh-tok",
            ),
            patch(
                "harnessbox.names.generate_workspace_name",
                return_value="tokyo",
            ),
        ):
            config = build_workspace_config(req)
        assert config.workspace is not None
        assert config.workspace.branch == "tokyo"
        assert config.workspace.base_branch == "main"
        assert config.workspace.clone_dir_name == "tokyo"

    def test_timeout_clamping(self) -> None:
        req = self._make_request(sandbox_timeout=600, session_timeout=700)
        with (
            patch("harnessbox._server.workspace_factory.inject_host_env_vars"),
            patch(
                "harnessbox._server.workspace_factory.inject_host_credential_files",
                return_value={},
            ),
            patch(
                "harnessbox._server.workspace_factory.extract_provider_key",
                return_value=None,
            ),
        ):
            config = build_workspace_config(req)
        assert config.session_timeout == 540  # max(600 - 60, 0)
        assert config.timeout == 600

    def test_security_policy_construction(self) -> None:
        from harnessbox.server import SecurityPolicyRequest

        req = self._make_request(
            security_policy=SecurityPolicyRequest(
                denied_tools=["bash"],
                deny_network=True,
            )
        )
        with (
            patch("harnessbox._server.workspace_factory.inject_host_env_vars"),
            patch(
                "harnessbox._server.workspace_factory.inject_host_credential_files",
                return_value={},
            ),
            patch(
                "harnessbox._server.workspace_factory.extract_provider_key",
                return_value=None,
            ),
        ):
            config = build_workspace_config(req)
        assert config.security_policy is not None
        assert config.security_policy.denied_tools == ["bash"]
        assert config.security_policy.deny_network is True
