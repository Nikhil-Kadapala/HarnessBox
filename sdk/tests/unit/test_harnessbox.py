"""Tests for HarnessBox — the public API wrapper."""

import pytest

from harnessbox.harnessbox import (
    FileSystemConfig,
    HarnessBox,
    HarnessBoxSecrets,
    Session,
    WorkspaceConfig,
    WorkspaceMode,
)
from harnessbox.workspace import GitRepoConfig


class TestHarnessBoxInit:
    def test_minimal_construction(self):
        hb = HarnessBox(provider="e2b")
        assert hb._provider == "e2b"
        assert hb._harness == "claude-code"
        assert hb._manager is None

    def test_with_workspace_config_creates_manager(self, mock_provider):
        hb = HarnessBox(
            provider=mock_provider,
            workspace_config=WorkspaceConfig(),
        )
        assert hb._manager is not None

    def test_without_workspace_config_no_manager(self, mock_provider):
        hb = HarnessBox(provider=mock_provider)
        assert hb._manager is None

    def test_secrets_from_dict(self):
        hb = HarnessBox(
            provider="e2b",
            secrets={
                "provider_api_key": "e2b_key_123",
                "harness_secrets": {"ANTHROPIC_API_KEY": "sk-ant-123"},
            },
        )
        assert hb._secrets.provider_api_key == "e2b_key_123"
        assert hb._secrets.harness_secrets == {"ANTHROPIC_API_KEY": "sk-ant-123"}

    def test_secrets_from_dataclass(self):
        s = HarnessBoxSecrets(
            provider_api_key="e2b_key_456",
            harness_secrets={"GITHUB_TOKEN": "ghp_abc"},
        )
        hb = HarnessBox(provider="e2b", secrets=s)
        assert hb._secrets.provider_api_key == "e2b_key_456"
        assert hb._secrets.harness_secrets == {"GITHUB_TOKEN": "ghp_abc"}

    def test_secrets_none_defaults(self):
        hb = HarnessBox(provider="e2b")
        assert hb._secrets.provider_api_key is None
        assert hb._secrets.harness_secrets is None

    def test_env_vars_preserved(self):
        hb = HarnessBox(provider="e2b", env_vars={"MY_VAR": "hello"})
        assert hb._env_vars == {"MY_VAR": "hello"}

    def test_accepts_provider_instance(self, mock_provider):
        hb = HarnessBox(provider=mock_provider)
        assert hb._provider is mock_provider


class TestWorkspaceConfig:
    def test_workspace_mode_enum_values(self):
        assert WorkspaceMode.NEW == "new"
        assert WorkspaceMode.SHARED == "shared"

    def test_default_workspace_config(self):
        cfg = WorkspaceConfig()
        assert cfg.workspace_mode == WorkspaceMode.NEW
        assert cfg.git_repo_config is None
        assert cfg.file_system_config is None

    def test_workspace_config_with_git(self):
        cfg = WorkspaceConfig(
            git_repo_config=GitRepoConfig(
                remote="https://github.com/org/repo.git",
                branch="feat/test",
                base_branch="main",
            ),
        )
        assert cfg.git_repo_config is not None
        assert cfg.git_repo_config.remote == "https://github.com/org/repo.git"

    def test_file_system_config_placeholder(self):
        cfg = WorkspaceConfig(file_system_config=FileSystemConfig())
        assert cfg.file_system_config is not None


class TestSession:
    async def test_create_session_returns_session(self, mock_provider):
        hb = HarnessBox(
            provider=mock_provider,
            workspace_config=WorkspaceConfig(),
        )
        session = await hb.create_session()
        assert isinstance(session, Session)
        assert session.id is not None

    async def test_create_session_requires_workspace_config(self, mock_provider):
        hb = HarnessBox(provider=mock_provider)
        with pytest.raises(RuntimeError, match="requires workspace_config"):
            await hb.create_session()

    async def test_session_sandbox_id(self, mock_provider):
        hb = HarnessBox(
            provider=mock_provider,
            workspace_config=WorkspaceConfig(),
        )
        session = await hb.create_session()
        assert session.sandbox_id == "mock-sandbox-123"

    async def test_create_session_branch_override(self, mock_provider):
        hb = HarnessBox(
            provider=mock_provider,
            workspace_config=WorkspaceConfig(
                git_repo_config=GitRepoConfig(
                    remote="https://github.com/org/repo.git",
                    branch="feat/default",
                    base_branch="main",
                ),
            ),
        )
        session = await hb.create_session(branch="feat/override")
        assert session.branch == "feat/override"

    async def test_create_session_uses_config_branch(self, mock_provider):
        hb = HarnessBox(
            provider=mock_provider,
            workspace_config=WorkspaceConfig(
                git_repo_config=GitRepoConfig(
                    remote="https://github.com/org/repo.git",
                    branch="feat/from-config",
                    base_branch="main",
                ),
            ),
        )
        session = await hb.create_session()
        assert session.branch == "feat/from-config"

    async def test_create_session_no_config_no_branch_defaults_main(self, mock_provider):
        hb = HarnessBox(
            provider=mock_provider,
            workspace_config=WorkspaceConfig(),
        )
        session = await hb.create_session()
        assert session.branch == "main"

    async def test_create_multiple_sessions(self, mock_provider):
        hb = HarnessBox(
            provider=mock_provider,
            workspace_config=WorkspaceConfig(),
        )
        s1 = await hb.create_session(branch="feat/auth")
        s2 = await hb.create_session(branch="feat/ui")
        assert s1.id != s2.id
        assert s1.branch == "feat/auth"
        assert s2.branch == "feat/ui"

    async def test_session_status_running(self, mock_provider):
        from harnessbox.lifecycle import SessionStatus

        hb = HarnessBox(
            provider=mock_provider,
            workspace_config=WorkspaceConfig(),
        )
        session = await hb.create_session()
        assert session.status == SessionStatus.RUNNING

    async def test_session_status_killed_after_kill(self, mock_provider):
        from harnessbox.lifecycle import SessionStatus

        hb = HarnessBox(
            provider=mock_provider,
            workspace_config=WorkspaceConfig(),
        )
        session = await hb.create_session()
        await session.kill()
        assert session.status == SessionStatus.KILLED

    async def test_session_kill_idempotent(self, mock_provider):
        from harnessbox.lifecycle import SessionStatus

        hb = HarnessBox(
            provider=mock_provider,
            workspace_config=WorkspaceConfig(),
        )
        session = await hb.create_session()
        await session.kill()
        await session.kill()
        assert session.status == SessionStatus.KILLED

    async def test_session_run_command(self, mock_provider):
        hb = HarnessBox(
            provider=mock_provider,
            workspace_config=WorkspaceConfig(),
        )
        session = await hb.create_session()
        result = await session.run_command("echo hello")
        assert result.exit_code == 0
        assert "echo hello" in mock_provider._commands

    async def test_session_run_command_after_kill_raises(self, mock_provider):
        hb = HarnessBox(
            provider=mock_provider,
            workspace_config=WorkspaceConfig(),
        )
        session = await hb.create_session()
        await session.kill()
        from harnessbox.workspace_manager import WorkspaceNotFoundError

        with pytest.raises((WorkspaceNotFoundError, RuntimeError)):
            await session.run_command("echo test")

    async def test_hb_kill_shuts_down_all_sessions(self, mock_provider):
        hb = HarnessBox(
            provider=mock_provider,
            workspace_config=WorkspaceConfig(),
        )
        s1 = await hb.create_session(branch="feat/a")
        s2 = await hb.create_session(branch="feat/b")
        await hb.kill()
        from harnessbox.lifecycle import SessionStatus

        assert s1.status == SessionStatus.KILLED
        assert s2.status == SessionStatus.KILLED

    async def test_context_manager_no_op_enter(self, mock_provider):
        async with HarnessBox(
            provider=mock_provider,
            workspace_config=WorkspaceConfig(),
        ) as hb:
            assert hb._manager is not None
            session = await hb.create_session()
            assert session.sandbox_id == "mock-sandbox-123"

    async def test_build_workspace_config_maps_params(self, mock_provider):
        hb = HarnessBox(
            provider=mock_provider,
            harness="codex",
            workspace_config=WorkspaceConfig(
                git_repo_config=GitRepoConfig(
                    remote="https://github.com/user/repo.git",
                    branch="main",
                    base_branch="main",
                ),
            ),
            model="gpt-4",
            setup_script="npm install",
            timeout=600,
            secrets={
                "provider_api_key": "e2b_key",
                "harness_secrets": {"ANTHROPIC_API_KEY": "sk-ant"},
            },
        )
        config = hb._build_workspace_config("feat/test")
        assert config.harness == "codex"
        assert config.model == "gpt-4"
        assert config.setup_script == "npm install"
        assert config.timeout == 600
        assert config.skip_permissions is True
        assert config.env_vars.get("ANTHROPIC_API_KEY") == "sk-ant"
        assert config.workspace is not None
        assert config.workspace.branch == "feat/test"

    async def test_build_workspace_config_no_git(self, mock_provider):
        hb = HarnessBox(
            provider=mock_provider,
            workspace_config=WorkspaceConfig(),
        )
        config = hb._build_workspace_config("main")
        assert config.workspace is None
