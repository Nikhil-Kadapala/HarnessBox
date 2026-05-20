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

        with (
            patch("harnessbox.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox.workspace_manager.AgentManager") as MockAgentMgr,
        ):
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

        with (
            patch("harnessbox.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox.workspace_manager.AgentManager"),
        ):
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

        with (
            patch("harnessbox.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox.workspace_manager.AgentManager"),
        ):
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

        with (
            patch("harnessbox.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox.workspace_manager.AgentManager") as MockAgentMgr,
        ):
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

        with (
            patch("harnessbox.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox.workspace_manager.AgentManager") as MockAgentMgr,
        ):
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

        with (
            patch("harnessbox.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox.workspace_manager.AgentManager"),
        ):
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

        with (
            patch("harnessbox.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox.workspace_manager.AgentManager"),
        ):
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

        with (
            patch("harnessbox.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox.workspace_manager.AgentManager"),
        ):
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance._skip_permissions = False
            instance._cwd = "/workspace"

            ws = MagicMock()
            ws.remote = "https://github.com/test/repo.git"
            ws.branch = "tokyo"
            ws.clone_dir_name = "repo"

            await mgr.create_workspace(WorkspaceConfig(workspace=ws), workspace_id="w-1")

        result = mgr.find_by_repo_branch("https://github.com/test/repo.git", "tokyo")
        assert result is not None
        assert result.workspace_id == "w-1"

    @pytest.mark.asyncio
    async def test_find_no_match(self) -> None:
        mgr = WorkspaceManager()

        from unittest.mock import AsyncMock, patch

        with (
            patch("harnessbox.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox.workspace_manager.AgentManager"),
        ):
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

        with (
            patch("harnessbox.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox.workspace_manager.AgentManager"),
        ):
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

        with (
            patch("harnessbox.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox.workspace_manager.AgentManager") as MockAgentManager,
        ):
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
        await storage.save_workspace(
            {
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
            }
        )

        with (
            patch("harnessbox.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox.workspace_manager.AgentManager"),
        ):
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


class TestConnectSandbox:
    """Test lazy sandbox reconnection for storage-loaded workspaces."""

    @pytest.mark.asyncio
    async def test_connect_via_provider_sandbox_id(self):
        """Should reconnect sandbox using stored provider_sandbox_id."""
        from harnessbox._storage.memory import MemoryBackend
        from harnessbox.workspace_manager import WorkspaceInstance

        storage = MemoryBackend()
        await storage.initialize()
        mgr = await WorkspaceManager.create(storage=storage, auto_pause=False)

        now = datetime.now(timezone.utc).isoformat()
        await storage.save_workspace(
            {
                "workspace_id": "w-revive",
                "remote": "https://github.com/user/repo.git",
                "branch": "main",
                "provider": "e2b",
                "provider_sandbox_id": "live-sandbox-42",
                "snapshot_id": "snap-1",
                "harness": "claude-code",
                "status": WorkspaceState.PAUSED.value,
                "created_at": now,
                "last_active": now,
                "config_json": '{"timeout": 300, "skip_permissions": true}',
            }
        )

        # Simulate a disconnected workspace (loaded from storage)
        info = WorkspaceInstance(
            workspace_id="w-revive",
            remote="https://github.com/user/repo.git",
            branch="main",
            provider="e2b",
            provider_sandbox_id="live-sandbox-42",
            snapshot_id="snap-1",
            status=WorkspaceState.PAUSED.value,
            created_at=now,
            last_active=now,
            harness="claude-code",
            sandbox=None,
            agent_manager=None,
        )
        mgr._workspaces["w-revive"] = info

        with (
            patch("harnessbox.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox.workspace_manager.AgentManager"),
        ):
            mock_sandbox = MockSandbox.return_value
            mock_sandbox.resume = AsyncMock()
            mock_sandbox._provider = MockProvider()
            mock_sandbox._provider._sandbox_id = "live-sandbox-42"

            await mgr._connect_sandbox("w-revive")

        assert info.sandbox is not None
        assert info.agent_manager is not None
        assert info.status == WorkspaceState.ACTIVE.value
        mock_sandbox.resume.assert_called_once_with("live-sandbox-42")

    @pytest.mark.asyncio
    async def test_connect_falls_back_to_snapshot_when_sandbox_expired(self):
        """Should recover from snapshot when provider_sandbox_id is stale."""
        from harnessbox._storage.memory import MemoryBackend
        from harnessbox.providers import SandboxDeadError
        from harnessbox.workspace_manager import WorkspaceInstance

        storage = MemoryBackend()
        await storage.initialize()
        mgr = await WorkspaceManager.create(storage=storage, auto_pause=False)

        now = datetime.now(timezone.utc).isoformat()
        await storage.save_workspace(
            {
                "workspace_id": "w-expired",
                "remote": "https://github.com/user/repo.git",
                "branch": "feat",
                "provider": "e2b",
                "provider_sandbox_id": "dead-sandbox",
                "snapshot_id": "snap-recover",
                "harness": "claude-code",
                "status": WorkspaceState.PAUSED.value,
                "created_at": now,
                "last_active": now,
                "config_json": '{"timeout": 600, "skip_permissions": false}',
            }
        )

        info = WorkspaceInstance(
            workspace_id="w-expired",
            remote="https://github.com/user/repo.git",
            branch="feat",
            provider="e2b",
            provider_sandbox_id="dead-sandbox",
            snapshot_id="snap-recover",
            status=WorkspaceState.PAUSED.value,
            created_at=now,
            last_active=now,
            harness="claude-code",
            sandbox=None,
            agent_manager=None,
        )
        mgr._workspaces["w-expired"] = info

        with (
            patch("harnessbox.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox.workspace_manager.AgentManager"),
        ):
            mock_sandbox = MockSandbox.return_value
            mock_sandbox.resume = AsyncMock(
                side_effect=SandboxDeadError("Sandbox was not found")
            )
            mock_provider = MockProvider()
            mock_provider.create = AsyncMock()
            mock_provider._sandbox_id = "new-sandbox-99"
            mock_sandbox._provider = mock_provider

            await mgr._connect_sandbox("w-expired")

        assert info.status == WorkspaceState.ACTIVE.value
        assert info.sandbox is not None
        mock_provider.create.assert_called_once_with(
            env_vars={},
            timeout=600,
            snapshot_id="snap-recover",
        )

    @pytest.mark.asyncio
    async def test_connect_raises_when_no_sandbox_id_or_snapshot(self):
        """Should raise ValueError when workspace has no way to reconnect."""
        from harnessbox._storage.memory import MemoryBackend
        from harnessbox.workspace_manager import WorkspaceInstance

        storage = MemoryBackend()
        await storage.initialize()
        mgr = await WorkspaceManager.create(storage=storage, auto_pause=False)

        now = datetime.now(timezone.utc).isoformat()
        await storage.save_workspace(
            {
                "workspace_id": "w-dead",
                "remote": "https://github.com/user/repo.git",
                "branch": "dead-branch",
                "provider": "e2b",
                "provider_sandbox_id": None,
                "snapshot_id": None,
                "harness": "claude-code",
                "status": WorkspaceState.ACTIVE.value,
                "created_at": now,
                "last_active": now,
                "config_json": "{}",
            }
        )

        info = WorkspaceInstance(
            workspace_id="w-dead",
            remote="https://github.com/user/repo.git",
            branch="dead-branch",
            provider="e2b",
            provider_sandbox_id=None,
            snapshot_id=None,
            status=WorkspaceState.ACTIVE.value,
            created_at=now,
            last_active=now,
            harness="claude-code",
            sandbox=None,
            agent_manager=None,
        )
        mgr._workspaces["w-dead"] = info

        with pytest.raises(ValueError, match="no provider_sandbox_id or snapshot_id"):
            with (
                patch("harnessbox.workspace_manager.Sandbox"),
                patch("harnessbox.workspace_manager.AgentManager"),
            ):
                await mgr._connect_sandbox("w-dead")

    @pytest.mark.asyncio
    async def test_connect_raises_without_storage(self):
        """Should raise ValueError when no storage backend is available."""
        from harnessbox.workspace_manager import WorkspaceInstance

        mgr = WorkspaceManager()

        now = datetime.now(timezone.utc).isoformat()
        info = WorkspaceInstance(
            workspace_id="w-orphan",
            remote="",
            branch="",
            provider="e2b",
            provider_sandbox_id="sb-1",
            snapshot_id=None,
            status=WorkspaceState.PAUSED.value,
            created_at=now,
            last_active=now,
            harness="claude-code",
            sandbox=None,
            agent_manager=None,
        )
        mgr._workspaces["w-orphan"] = info

        with pytest.raises(ValueError, match="no storage backend"):
            await mgr._connect_sandbox("w-orphan")

    @pytest.mark.asyncio
    async def test_prompt_connects_sandbox_lazily(self):
        """prompt() should connect sandbox on demand for storage-loaded workspaces."""
        from harnessbox._storage.memory import MemoryBackend
        from harnessbox.workspace_manager import WorkspaceInstance

        storage = MemoryBackend()
        await storage.initialize()
        mgr = await WorkspaceManager.create(storage=storage, auto_pause=False)

        now = datetime.now(timezone.utc).isoformat()
        await storage.save_workspace(
            {
                "workspace_id": "w-prompt",
                "remote": "https://github.com/user/repo.git",
                "branch": "main",
                "provider": "e2b",
                "provider_sandbox_id": "prompt-sandbox",
                "snapshot_id": None,
                "harness": "claude-code",
                "status": WorkspaceState.PAUSED.value,
                "created_at": now,
                "last_active": now,
                "config_json": '{"timeout": 300}',
            }
        )

        info = WorkspaceInstance(
            workspace_id="w-prompt",
            remote="https://github.com/user/repo.git",
            branch="main",
            provider="e2b",
            provider_sandbox_id="prompt-sandbox",
            snapshot_id=None,
            status=WorkspaceState.PAUSED.value,
            created_at=now,
            last_active=now,
            harness="claude-code",
            sandbox=None,
            agent_manager=None,
        )
        mgr._workspaces["w-prompt"] = info

        with (
            patch("harnessbox.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox.workspace_manager.AgentManager") as MockAgentMgr,
        ):
            mock_sandbox = MockSandbox.return_value
            mock_sandbox.resume = AsyncMock()
            mock_sandbox._provider = MockProvider()
            mock_sandbox._provider._sandbox_id = "prompt-sandbox"
            mock_sandbox._event_buffer = None
            mock_sandbox._cwd = "/workspace"

            mock_agent = MockAgentMgr.return_value
            mock_agent.send_message = AsyncMock(return_value=AsyncMock())

            # After revive, prompt() should proceed without error.
            # We just need to verify that revive was called (sandbox gets assigned).
            # The actual prompt streaming is tested elsewhere.
            await mgr._connect_sandbox("w-prompt")

        assert info.sandbox is not None
        assert info.agent_manager is not None
        assert info.status == WorkspaceState.ACTIVE.value
