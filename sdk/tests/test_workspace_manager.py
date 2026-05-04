"""Tests for harnessbox.workspace_manager — WorkspaceManager + WorkspaceConfig."""

from __future__ import annotations

import pytest

from harnessbox.lifecycle import InvalidTransitionError
from harnessbox.workspace_manager import WorkspaceConfig, WorkspaceManager, WorkspaceNotFoundError

from .conftest import MockProvider


@pytest.fixture
def mock_provider() -> MockProvider:
    return MockProvider()


class TestWorkspaceConfig:
    def test_defaults(self) -> None:
        config = WorkspaceConfig()
        assert config.provider == "e2b"
        assert config.harness == "claude-code"
        assert config.timeout == 300
        assert config.skip_permissions is False

    def test_custom_values(self) -> None:
        config = WorkspaceConfig(
            provider="e2b",
            harness="claude-code",
            env_vars={"KEY": "val"},
            skip_permissions=True,
        )
        assert config.env_vars == {"KEY": "val"}
        assert config.skip_permissions is True


class TestWorkspaceManager:
    @pytest.mark.asyncio
    async def test_create_workspace(self, mock_provider: MockProvider) -> None:
        mgr = WorkspaceManager()
        config = WorkspaceConfig()

        from unittest.mock import AsyncMock, patch

        with patch("harnessbox.workspace_manager.Sandbox") as MockSandbox, \
             patch("harnessbox.workspace_manager.AgentManager") as MockAgentMgr:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance.sandbox_id = "sb-1"
            instance._skip_permissions = False
            instance._cwd = "/workspace"
            MockAgentMgr.return_value = None

            info = await mgr.create_workspace(config, workspace_id="test-1")

        assert info.workspace_id == "test-1"
        assert info.harness == "claude-code"
        assert info.status == "active"

    @pytest.mark.asyncio
    async def test_get_workspace(self, mock_provider: MockProvider) -> None:
        mgr = WorkspaceManager()
        config = WorkspaceConfig()

        from unittest.mock import AsyncMock, patch

        with patch("harnessbox.workspace_manager.Sandbox") as MockSandbox, \
             patch("harnessbox.workspace_manager.AgentManager"):
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance._skip_permissions = False
            instance._cwd = "/workspace"
            await mgr.create_workspace(config, workspace_id="w-1")

        info = mgr.get_workspace("w-1")
        assert info.workspace_id == "w-1"

    def test_get_workspace_not_found(self) -> None:
        mgr = WorkspaceManager()
        with pytest.raises(WorkspaceNotFoundError):
            mgr.get_workspace("nonexistent")

    @pytest.mark.asyncio
    async def test_list_workspaces(self) -> None:
        mgr = WorkspaceManager()

        from unittest.mock import AsyncMock, patch

        with patch("harnessbox.workspace_manager.Sandbox") as MockSandbox, \
             patch("harnessbox.workspace_manager.AgentManager"):
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance._skip_permissions = False
            instance._cwd = "/workspace"
            await mgr.create_workspace(WorkspaceConfig(), workspace_id="w-1")
            await mgr.create_workspace(WorkspaceConfig(), workspace_id="w-2")

        workspaces = mgr.list_workspaces()
        assert len(workspaces) == 2
        ids = {w.workspace_id for w in workspaces}
        assert ids == {"w-1", "w-2"}

    @pytest.mark.asyncio
    async def test_destroy_workspace(self) -> None:
        mgr = WorkspaceManager()

        from unittest.mock import AsyncMock, patch

        with patch("harnessbox.workspace_manager.Sandbox") as MockSandbox, \
             patch("harnessbox.workspace_manager.AgentManager") as MockAgentMgr:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance.kill = AsyncMock()
            instance._skip_permissions = False
            instance._cwd = "/workspace"

            agent_mgr = MockAgentMgr.return_value
            agent_mgr.shutdown_all = AsyncMock()

            await mgr.create_workspace(WorkspaceConfig(), workspace_id="w-1")

        await mgr.destroy_workspace("w-1")
        assert len(mgr.list_workspaces()) == 0

    @pytest.mark.asyncio
    async def test_destroy_nonexistent_raises(self) -> None:
        mgr = WorkspaceManager()
        with pytest.raises(WorkspaceNotFoundError):
            await mgr.destroy_workspace("nope")

    @pytest.mark.asyncio
    async def test_shutdown_all(self) -> None:
        mgr = WorkspaceManager()

        from unittest.mock import AsyncMock, patch

        with patch("harnessbox.workspace_manager.Sandbox") as MockSandbox, \
             patch("harnessbox.workspace_manager.AgentManager") as MockAgentMgr:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance.kill = AsyncMock()
            instance._skip_permissions = False
            instance._cwd = "/workspace"

            agent_mgr = MockAgentMgr.return_value
            agent_mgr.shutdown_all = AsyncMock()

            await mgr.create_workspace(WorkspaceConfig(), workspace_id="w-1")
            await mgr.create_workspace(WorkspaceConfig(), workspace_id="w-2")

        await mgr.shutdown_all()
        assert len(mgr.list_workspaces()) == 0


class TestTransitionWorkspace:
    @pytest.mark.asyncio
    async def test_valid_transition(self) -> None:
        mgr = WorkspaceManager()

        from unittest.mock import AsyncMock, patch

        with patch("harnessbox.workspace_manager.Sandbox") as MockSandbox, \
             patch("harnessbox.workspace_manager.AgentManager"):
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance._skip_permissions = False
            instance._cwd = "/workspace"
            await mgr.create_workspace(WorkspaceConfig(), workspace_id="w-1")

        info = mgr.transition_workspace("w-1", "in_review")
        assert info.status == "in_review"

    @pytest.mark.asyncio
    async def test_invalid_transition_raises(self) -> None:
        mgr = WorkspaceManager()

        from unittest.mock import AsyncMock, patch

        with patch("harnessbox.workspace_manager.Sandbox") as MockSandbox, \
             patch("harnessbox.workspace_manager.AgentManager"):
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance._skip_permissions = False
            instance._cwd = "/workspace"
            await mgr.create_workspace(WorkspaceConfig(), workspace_id="w-1")

        with pytest.raises(InvalidTransitionError):
            mgr.transition_workspace("w-1", "merged")

    def test_transition_unknown_workspace_raises(self) -> None:
        mgr = WorkspaceManager()
        with pytest.raises(WorkspaceNotFoundError):
            mgr.transition_workspace("nope", "in_review")


class TestFindByRepoBranch:
    @pytest.mark.asyncio
    async def test_find_matching_workspace(self) -> None:
        mgr = WorkspaceManager()

        from unittest.mock import AsyncMock, MagicMock, patch

        with patch("harnessbox.workspace_manager.Sandbox") as MockSandbox, \
             patch("harnessbox.workspace_manager.AgentManager"):
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance._skip_permissions = False
            instance._cwd = "/workspace"

            ws = MagicMock()
            ws.remote = "https://github.com/test/repo.git"
            ws.branch = "tokyo"
            ws.clone_dir_name = "repo"

            await mgr.create_workspace(
                WorkspaceConfig(workspace=ws), workspace_id="w-1"
            )

        result = mgr.find_by_repo_branch("https://github.com/test/repo.git", "tokyo")
        assert result is not None
        assert result.workspace_id == "w-1"

    @pytest.mark.asyncio
    async def test_find_no_match(self) -> None:
        mgr = WorkspaceManager()

        from unittest.mock import AsyncMock, patch

        with patch("harnessbox.workspace_manager.Sandbox") as MockSandbox, \
             patch("harnessbox.workspace_manager.AgentManager"):
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance._skip_permissions = False
            instance._cwd = "/workspace"
            await mgr.create_workspace(WorkspaceConfig(), workspace_id="w-1")

        result = mgr.find_by_repo_branch("https://github.com/other/repo.git", "main")
        assert result is None
