"""Tests for HarnessBox — the public API wrapper."""

from harnessbox.harnessbox import (
    HarnessBox,
    HarnessBoxSecrets,
    Session,
    WorkspaceConfig,
)
from harnessbox.workspace import GitRepoConfig


class TestHarnessBoxInit:
    def test_minimal_construction(self):
        hb = HarnessBox(provider="e2b")
        assert hb._provider == "e2b"
        assert hb._harness == "claude-code"
        assert hb._sessions == {}

    def test_with_workspace_config(self, mock_provider):
        hb = HarnessBox(
            provider=mock_provider,
            workspace_config=WorkspaceConfig(),
        )
        assert hb._workspace_config is not None
        assert hb._sessions == {}

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
    def test_default_workspace_config(self):
        cfg = WorkspaceConfig()
        assert cfg.git_repo_config is None

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


class TestSession:
    async def test_create_session_returns_session(self, mock_provider):
        hb = HarnessBox(
            provider=mock_provider,
            workspace_config=WorkspaceConfig(),
        )
        session = await hb.create_session()
        assert isinstance(session, Session)
        assert session.id is not None

    async def test_create_session_stores_in_sessions(self, mock_provider):
        hb = HarnessBox(
            provider=mock_provider,
            workspace_config=WorkspaceConfig(),
        )
        session = await hb.create_session()
        assert session.id in hb._sessions

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
        assert len(hb._sessions) == 2

    async def test_session_status_running(self, mock_provider):
        from harnessbox.lifecycle import RuntimeState

        hb = HarnessBox(
            provider=mock_provider,
            workspace_config=WorkspaceConfig(),
        )
        session = await hb.create_session()
        assert session.status == RuntimeState.ACTIVE

    async def test_session_status_killed_after_kill(self, mock_provider):
        from harnessbox.lifecycle import RuntimeState

        hb = HarnessBox(
            provider=mock_provider,
            workspace_config=WorkspaceConfig(),
        )
        session = await hb.create_session()
        await session.kill()
        assert session.status == RuntimeState.DEAD

    async def test_session_kill_idempotent(self, mock_provider):
        from harnessbox.lifecycle import RuntimeState

        hb = HarnessBox(
            provider=mock_provider,
            workspace_config=WorkspaceConfig(),
        )
        session = await hb.create_session()
        await session.kill()
        await session.kill()
        assert session.status == RuntimeState.DEAD

    async def test_session_run_command(self, mock_provider):
        hb = HarnessBox(
            provider=mock_provider,
            workspace_config=WorkspaceConfig(),
        )
        session = await hb.create_session()
        result = await session.run_command("echo hello")
        assert result.exit_code == 0
        assert "echo hello" in mock_provider._commands

    async def test_session_send_message_delegates_to_sandbox(self, mock_provider):
        hb = HarnessBox(
            provider=mock_provider,
            workspace_config=WorkspaceConfig(),
        )
        session = await hb.create_session()
        # send_message delegates to sandbox — assert the generator is returned
        gen = session.send_message("do something")
        assert hasattr(gen, "__aiter__")

    async def test_hb_kill_shuts_down_all_sessions(self, mock_provider):
        from harnessbox.lifecycle import RuntimeState

        hb = HarnessBox(
            provider=mock_provider,
            workspace_config=WorkspaceConfig(),
        )
        s1 = await hb.create_session(branch="feat/a")
        s2 = await hb.create_session(branch="feat/b")
        await hb.kill()
        assert s1.status == RuntimeState.DEAD
        assert s2.status == RuntimeState.DEAD
        assert hb._sessions == {}

    async def test_context_manager_kills_on_exit(self, mock_provider):
        from harnessbox.lifecycle import RuntimeState

        async with HarnessBox(
            provider=mock_provider,
            workspace_config=WorkspaceConfig(),
        ) as hb:
            session = await hb.create_session()
            assert session.sandbox_id == "mock-sandbox-123"
        assert session.status == RuntimeState.DEAD

    async def test_sandbox_lock_does_not_wrap_send_message(self, mock_provider):
        """Lifecycle lock must not deadlock send_message during streaming."""

        hb = HarnessBox(
            provider=mock_provider,
            workspace_config=WorkspaceConfig(),
        )
        session = await hb.create_session()
        sandbox = session.sandbox
        # Acquiring the lock should not block send_message — lock is for lifecycle only
        async with sandbox._lock:
            # send_message does NOT acquire _lock, so this should not deadlock
            gen = sandbox.send_message("test")
            assert hasattr(gen, "__aiter__")
