"""Tests for harnessbox.workspace_manager — WorkspaceManager + WorkspaceConfig."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from harnessbox.lifecycle import InvalidTransitionError, WorkspaceState
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


class TestWorkspacePooling:
    """Test branch-based workspace pooling."""

    @pytest.mark.asyncio
    async def test_get_or_create_creates_when_no_match(self):
        """Should create new workspace when no paused workspace matches."""
        from harnessbox.workspace import GitWorkspace

        mgr = WorkspaceManager()
        workspace = GitWorkspace(
            remote="https://github.com/user/repo.git",
            branch="main",
        )
        config = WorkspaceConfig(workspace=workspace)

        with patch("harnessbox.workspace_manager.Sandbox") as MockSandbox, \
             patch("harnessbox.workspace_manager.AgentManager"):
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance._skip_permissions = False
            instance._cwd = "/workspace"
            instance._workspace = workspace

            result = await mgr.get_or_create_workspace(
                "https://github.com/user/repo.git",
                "main",
                config=config,
            )

        assert result.remote == "https://github.com/user/repo.git"
        assert result.branch == "main"
        assert result.status == WorkspaceState.ACTIVE.value

    @pytest.mark.asyncio
    async def test_get_or_create_resumes_paused_in_memory(self):
        """Should resume paused workspace if found in memory."""
        from harnessbox.workspace import GitWorkspace

        mgr = WorkspaceManager()
        workspace = GitWorkspace(
            remote="https://github.com/user/repo.git",
            branch="main",
        )
        config = WorkspaceConfig(workspace=workspace)

        with patch("harnessbox.workspace_manager.Sandbox") as MockSandbox, \
             patch("harnessbox.workspace_manager.AgentManager") as MockAgentManager:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance.pause = AsyncMock(return_value="paused-id")
            instance.resume = AsyncMock()
            instance.create_snapshot = AsyncMock(return_value="snapshot-123")
            instance._skip_permissions = False
            instance._cwd = "/workspace"
            instance._workspace = workspace

            agent_mgr_instance = MockAgentManager.return_value
            agent_mgr_instance.shutdown_all = AsyncMock()

            # Create workspace
            info = await mgr.create_workspace(config, workspace_id="w-1")

            # Pause it
            await mgr._pause_workspace("w-1")
            assert info.status == WorkspaceState.PAUSED.value

            # Pool hit: get_or_create should resume
            result = await mgr.get_or_create_workspace(
                info.remote,
                info.branch,
                config=config,
            )

        assert result.workspace_id == "w-1"
        assert result.status == WorkspaceState.ACTIVE.value
        instance.resume.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_or_create_requires_config_when_no_match(self):
        """Should raise ValueError if no match found and config is None."""
        mgr = WorkspaceManager()

        with pytest.raises(ValueError, match="No paused workspace found"):
            await mgr.get_or_create_workspace(
                "https://github.com/user/repo.git",
                "main",
                config=None,
            )

    @pytest.mark.asyncio
    async def test_get_or_create_loads_from_storage_when_not_in_memory(self):
        """Should hydrate and resume workspace from storage if not in memory."""
        from harnessbox._storage.memory import MemoryBackend

        storage = MemoryBackend()
        await storage.initialize()
        mgr = await WorkspaceManager.create(storage=storage, auto_pause=False)

        # Add a paused workspace directly to storage (not in memory)
        await storage.save_workspace({
            "workspace_id": "w-storage",
            "remote": "https://github.com/user/repo.git",
            "branch": "feature-branch",
            "provider": "e2b",
            "provider_sandbox_id": "storage-sandbox",
            "snapshot_id": "storage-snapshot",
            "harness": "claude-code",
            "status": WorkspaceState.PAUSED.value,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_active": datetime.now(timezone.utc).isoformat(),
            "config_json": '{"timeout": 300, "skip_permissions": false}',
        })

        with patch("harnessbox.workspace_manager.Sandbox") as MockSandbox, \
             patch("harnessbox.workspace_manager.AgentManager"):
            instance = MockSandbox.return_value
            instance.resume = AsyncMock()

            # Pool hit from storage: should hydrate and resume
            result = await mgr.get_or_create_workspace(
                "https://github.com/user/repo.git",
                "feature-branch",
            )

        assert result.workspace_id == "w-storage"
        assert result.status == WorkspaceState.ACTIVE.value
        instance.resume.assert_called_once_with("storage-sandbox")
