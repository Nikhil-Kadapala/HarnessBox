"""Tests for harnessbox.workspace_manager — WorkspaceManager + WorkspaceConfig."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from harnessbox._server.workspace_manager import (
    WorkspaceConfig,
    WorkspaceManager,
    WorkspaceNotFoundError,
)
from harnessbox.lifecycle import InvalidTransitionError, RuntimeState
from tests.conftest import MockProvider


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
            patch("harnessbox._server.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox._server.workspace_manager.AgentManager") as MockAgentMgr,
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
        assert info.runtime_state == "active"

    @pytest.mark.asyncio
    async def test_get_workspace(self, mock_provider: MockProvider) -> None:
        mgr = WorkspaceManager()
        config = WorkspaceConfig()

        from unittest.mock import AsyncMock, patch

        with (
            patch("harnessbox._server.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox._server.workspace_manager.AgentManager"),
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
            patch("harnessbox._server.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox._server.workspace_manager.AgentManager"),
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
            patch("harnessbox._server.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox._server.workspace_manager.AgentManager") as MockAgentMgr,
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
            patch("harnessbox._server.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox._server.workspace_manager.AgentManager") as MockAgentMgr,
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
            patch("harnessbox._server.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox._server.workspace_manager.AgentManager"),
        ):
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance._skip_permissions = False
            instance._cwd = "/workspace"
            await mgr.create_workspace(WorkspaceConfig(), workspace_id="w-1")

        info = mgr.transition_workflow("w-1", "in_review")
        assert info.workflow_state == "in_review"

    @pytest.mark.asyncio
    async def test_invalid_transition_raises(self) -> None:
        mgr = WorkspaceManager()

        from unittest.mock import AsyncMock, patch

        with (
            patch("harnessbox._server.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox._server.workspace_manager.AgentManager"),
        ):
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance._skip_permissions = False
            instance._cwd = "/workspace"
            await mgr.create_workspace(WorkspaceConfig(), workspace_id="w-1")

        with pytest.raises(InvalidTransitionError):
            mgr.transition_workflow("w-1", "merged")

    def test_transition_unknown_workspace_raises(self) -> None:
        mgr = WorkspaceManager()
        with pytest.raises(WorkspaceNotFoundError):
            mgr.transition_workflow("nope", "in_review")


class TestWorkflowTransitionMatrix:
    """Full valid/invalid workflow transition coverage for WorkspaceManager."""

    @pytest.fixture
    async def mgr_with_workspace(self) -> tuple[WorkspaceManager, str]:
        mgr = WorkspaceManager()
        with (
            patch("harnessbox._server.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox._server.workspace_manager.AgentManager"),
        ):
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance._skip_permissions = False
            instance._cwd = "/workspace"
            await mgr.create_workspace(WorkspaceConfig(), workspace_id="w-wf")
        return mgr, "w-wf"

    def _set_workflow_state(self, mgr: WorkspaceManager, wid: str, state: str) -> None:
        info = mgr.get_workspace(wid)
        info.workflow_state = state

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "current,target",
        [
            ("backlog", "in_progress"),
            ("backlog", "archived"),
            ("in_progress", "in_review"),
            ("in_progress", "archived"),
            ("in_review", "in_progress"),
            ("in_review", "merged"),
            ("in_review", "archived"),
            ("merged", "archived"),
        ],
    )
    async def test_valid_transitions(
        self,
        mgr_with_workspace: tuple[WorkspaceManager, str],
        current: str,
        target: str,
    ) -> None:
        mgr, wid = mgr_with_workspace
        self._set_workflow_state(mgr, wid, current)
        info = mgr.transition_workflow(wid, target)
        assert info.workflow_state == target

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "current,target",
        [
            ("backlog", "merged"),
            ("backlog", "in_review"),
            ("in_progress", "merged"),
            ("in_progress", "backlog"),
            ("in_review", "backlog"),
            ("merged", "in_progress"),
            ("merged", "in_review"),
            ("archived", "in_progress"),
            ("archived", "merged"),
            ("archived", "backlog"),
        ],
    )
    async def test_invalid_transitions(
        self,
        mgr_with_workspace: tuple[WorkspaceManager, str],
        current: str,
        target: str,
    ) -> None:
        mgr, wid = mgr_with_workspace
        self._set_workflow_state(mgr, wid, current)
        with pytest.raises(InvalidTransitionError):
            mgr.transition_workflow(wid, target)

    @pytest.mark.asyncio
    async def test_archived_is_terminal(
        self, mgr_with_workspace: tuple[WorkspaceManager, str]
    ) -> None:
        mgr, wid = mgr_with_workspace
        self._set_workflow_state(mgr, wid, "archived")
        for state in ("backlog", "in_progress", "in_review", "merged"):
            with pytest.raises(InvalidTransitionError):
                mgr.transition_workflow(wid, state)

    @pytest.mark.asyncio
    async def test_unknown_target_state_raises_value_error(
        self, mgr_with_workspace: tuple[WorkspaceManager, str]
    ) -> None:
        mgr, wid = mgr_with_workspace
        with pytest.raises(ValueError, match="Unknown workflow state"):
            mgr.transition_workflow(wid, "imaginary")


class TestFindByRepoBranch:
    @pytest.mark.asyncio
    async def test_find_matching_workspace(self) -> None:
        mgr = WorkspaceManager()

        from unittest.mock import AsyncMock, MagicMock, patch

        with (
            patch("harnessbox._server.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox._server.workspace_manager.AgentManager"),
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
            patch("harnessbox._server.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox._server.workspace_manager.AgentManager"),
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
        from harnessbox.workspace import GitRepoConfig

        mgr = WorkspaceManager()
        workspace = GitRepoConfig(
            remote="https://github.com/user/repo.git",
            branch="main",
        )
        config = WorkspaceConfig(workspace=workspace)

        with (
            patch("harnessbox._server.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox._server.workspace_manager.AgentManager"),
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
        assert result.runtime_state == RuntimeState.ACTIVE.value

    @pytest.mark.asyncio
    async def test_get_or_create_resumes_paused_in_memory(self):
        """Should resume paused workspace if found in memory."""
        from harnessbox.workspace import GitRepoConfig

        mgr = WorkspaceManager()
        workspace = GitRepoConfig(
            remote="https://github.com/user/repo.git",
            branch="main",
        )
        config = WorkspaceConfig(workspace=workspace)

        with (
            patch("harnessbox._server.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox._server.workspace_manager.AgentManager") as MockAgentManager,
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
            assert info.runtime_state == RuntimeState.PAUSED.value

            # Pool hit: get_or_create should resume
            result = await mgr.get_or_create_workspace(
                info.remote,
                info.branch,
                config=config,
            )

        assert result.workspace_id == "w-1"
        assert result.runtime_state == RuntimeState.ACTIVE.value
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
        from harnessbox._server._storage.memory import MemoryBackend

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
                "runtime_state": RuntimeState.PAUSED.value,
                "workflow_state": "in_progress",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_active": datetime.now(timezone.utc).isoformat(),
                "config_json": '{"timeout": 300, "skip_permissions": false}',
            }
        )

        with (
            patch("harnessbox._server.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox._server.workspace_manager.AgentManager"),
            patch.object(WorkspaceManager, "_resolve_provider_api_key", return_value="fake-key"),
        ):
            instance = MockSandbox.return_value
            instance.resume = AsyncMock()
            instance.event_buffer.hydrate = AsyncMock()
            instance.sandbox_id = "storage-sandbox"

            # Pool hit from storage: should hydrate and resume
            result = await mgr.get_or_create_workspace(
                "https://github.com/user/repo.git",
                "feature-branch",
            )

        assert result.workspace_id == "w-storage"
        assert result.runtime_state == RuntimeState.ACTIVE.value
        instance.resume.assert_called_once_with("storage-sandbox")


class TestResumeWorkspaceRaceCondition:
    """Verify resume_workspace checks state inside the lock (no TOCTOU race)."""

    @pytest.mark.asyncio
    async def test_concurrent_resume_one_wins(self) -> None:
        """Two concurrent resume_workspace calls: one succeeds, the other raises."""
        import asyncio

        from harnessbox.workspace import GitRepoConfig

        mgr = WorkspaceManager()
        workspace = GitRepoConfig(
            remote="https://github.com/test/repo.git",
            branch="main",
        )

        with (
            patch("harnessbox._server.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox._server.workspace_manager.AgentManager") as MockAgentManager,
        ):
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance.pause = AsyncMock(return_value="paused-id")
            instance.resume = AsyncMock()
            instance.create_snapshot = AsyncMock(return_value="snap-1")
            instance._skip_permissions = False
            instance._cwd = "/workspace"
            instance._workspace = workspace

            agent_mgr_instance = MockAgentManager.return_value
            agent_mgr_instance.shutdown_all = AsyncMock()

            config = WorkspaceConfig(workspace=workspace)
            await mgr.create_workspace(config, workspace_id="w-race")
            await mgr._pause_workspace("w-race")

            assert mgr.get_workspace("w-race").runtime_state == RuntimeState.PAUSED.value

            results = await asyncio.gather(
                mgr.resume_workspace("w-race"),
                mgr.resume_workspace("w-race"),
                return_exceptions=True,
            )

        successes = [r for r in results if r is None]
        errors = [r for r in results if isinstance(r, InvalidTransitionError)]
        assert len(successes) == 1
        assert len(errors) == 1

    @pytest.mark.asyncio
    async def test_internal_resume_skips_when_already_active(self) -> None:
        """_resume_workspace (internal) silently returns if not paused."""
        mgr = WorkspaceManager()

        with (
            patch("harnessbox._server.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox._server.workspace_manager.AgentManager"),
        ):
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance.resume = AsyncMock()
            instance._skip_permissions = False
            instance._cwd = "/workspace"
            instance._workspace = None

            config = WorkspaceConfig()
            await mgr.create_workspace(config, workspace_id="w-active")

        assert mgr.get_workspace("w-active").runtime_state == RuntimeState.ACTIVE.value
        await mgr._resume_workspace("w-active")
        assert mgr.get_workspace("w-active").runtime_state == RuntimeState.ACTIVE.value


class TestConnectSandbox:
    """Test lazy sandbox reconnection for storage-loaded workspaces."""

    @pytest.mark.asyncio
    async def test_connect_via_provider_sandbox_id(self):
        """Should reconnect sandbox using stored provider_sandbox_id."""
        from harnessbox._server._storage.memory import MemoryBackend
        from harnessbox._server.workspace_manager import WorkspaceInstance

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
                "runtime_state": RuntimeState.PAUSED.value,
                "workflow_state": "in_progress",
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
            runtime_state=RuntimeState.PAUSED.value,
            workflow_state="in_progress",
            created_at=now,
            last_active=now,
            harness="claude-code",
            sandbox_conn=None,
            agent_manager=None,
        )
        mgr._workspaces["w-revive"] = info

        with (
            patch("harnessbox._server.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox._server.workspace_manager.AgentManager"),
            patch.object(WorkspaceManager, "_resolve_provider_api_key", return_value="fake-key"),
        ):
            mock_sandbox = MockSandbox.return_value
            mock_sandbox.resume = AsyncMock()
            mock_sandbox.sandbox_id = "live-sandbox-42"
            mock_sandbox.event_buffer.hydrate = AsyncMock()

            await mgr._connect_sandbox("w-revive")

        assert info.sandbox_conn is not None
        assert info.agent_manager is not None
        assert info.runtime_state == RuntimeState.ACTIVE.value
        mock_sandbox.resume.assert_called_once_with("live-sandbox-42")

    @pytest.mark.asyncio
    async def test_connect_falls_back_to_snapshot_when_sandbox_expired(self):
        """Should recover from snapshot when provider_sandbox_id is stale."""
        from harnessbox._server._storage.memory import MemoryBackend
        from harnessbox._server.workspace_manager import WorkspaceInstance
        from harnessbox.providers import SandboxDeadError

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
                "runtime_state": RuntimeState.PAUSED.value,
                "workflow_state": "in_progress",
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
            runtime_state=RuntimeState.PAUSED.value,
            workflow_state="in_progress",
            created_at=now,
            last_active=now,
            harness="claude-code",
            sandbox_conn=None,
            agent_manager=None,
        )
        mgr._workspaces["w-expired"] = info

        with (
            patch("harnessbox._server.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox._server.workspace_manager.AgentManager"),
            patch.object(WorkspaceManager, "_resolve_provider_api_key", return_value="fake-key"),
        ):
            mock_sandbox = MockSandbox.return_value
            mock_sandbox.resume = AsyncMock(side_effect=SandboxDeadError("Sandbox was not found"))
            mock_provider = MockProvider()
            mock_provider.create = AsyncMock()
            mock_provider._sandbox_id = "new-sandbox-99"
            mock_sandbox._provider = mock_provider
            mock_sandbox.sandbox_id = "new-sandbox-99"
            mock_sandbox.event_buffer.hydrate = AsyncMock()

            await mgr._connect_sandbox("w-expired")

        assert info.runtime_state == RuntimeState.ACTIVE.value
        assert info.sandbox_conn is not None
        mock_provider.create.assert_called_once_with(
            env_vars={},
            timeout=600,
            snapshot_id="snap-recover",
        )

    @pytest.mark.asyncio
    async def test_connect_raises_when_no_sandbox_id_or_snapshot(self):
        """Should raise ValueError when workspace has no way to reconnect."""
        from harnessbox._server._storage.memory import MemoryBackend
        from harnessbox._server.workspace_manager import WorkspaceInstance

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
                "runtime_state": RuntimeState.ACTIVE.value,
                "workflow_state": "in_progress",
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
            runtime_state=RuntimeState.ACTIVE.value,
            workflow_state="in_progress",
            created_at=now,
            last_active=now,
            harness="claude-code",
            sandbox_conn=None,
            agent_manager=None,
        )
        mgr._workspaces["w-dead"] = info

        with pytest.raises(ValueError, match="no provider_sandbox_id or snapshot_id"):
            with (
                patch("harnessbox._server.workspace_manager.Sandbox"),
                patch("harnessbox._server.workspace_manager.AgentManager"),
                patch.object(
                    WorkspaceManager, "_resolve_provider_api_key", return_value="fake-key"
                ),
            ):
                await mgr._connect_sandbox("w-dead")

    @pytest.mark.asyncio
    async def test_connect_raises_without_storage(self):
        """Should raise ValueError when no storage backend is available."""
        from harnessbox._server.workspace_manager import WorkspaceInstance

        mgr = WorkspaceManager()

        now = datetime.now(timezone.utc).isoformat()
        info = WorkspaceInstance(
            workspace_id="w-orphan",
            remote="",
            branch="",
            provider="e2b",
            provider_sandbox_id="sb-1",
            snapshot_id=None,
            runtime_state=RuntimeState.PAUSED.value,
            workflow_state="in_progress",
            created_at=now,
            last_active=now,
            harness="claude-code",
            sandbox_conn=None,
            agent_manager=None,
        )
        mgr._workspaces["w-orphan"] = info

        with pytest.raises(ValueError, match="no storage backend"):
            await mgr._connect_sandbox("w-orphan")

    @pytest.mark.asyncio
    async def test_connect_raises_when_api_key_missing(self):
        """Should raise ValueError with actionable message when E2B API key is missing."""
        from harnessbox._server._storage.memory import MemoryBackend
        from harnessbox._server.workspace_manager import WorkspaceInstance

        storage = MemoryBackend()
        await storage.initialize()
        mgr = await WorkspaceManager.create(storage=storage, auto_pause=False)

        now = datetime.now(timezone.utc).isoformat()
        await storage.save_workspace(
            {
                "workspace_id": "w-nokey",
                "remote": "",
                "branch": "",
                "provider": "e2b",
                "provider_sandbox_id": "sb-1",
                "snapshot_id": None,
                "harness": "claude-code",
                "runtime_state": RuntimeState.PAUSED.value,
                "workflow_state": "in_progress",
                "created_at": now,
                "last_active": now,
                "config_json": '{"timeout": 300}',
            }
        )

        info = WorkspaceInstance(
            workspace_id="w-nokey",
            remote="",
            branch="",
            provider="e2b",
            provider_sandbox_id="sb-1",
            snapshot_id=None,
            runtime_state=RuntimeState.PAUSED.value,
            workflow_state="in_progress",
            created_at=now,
            last_active=now,
            harness="claude-code",
            sandbox_conn=None,
            agent_manager=None,
        )
        mgr._workspaces["w-nokey"] = info

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("pathlib.Path.is_file", return_value=False),
            patch("harnessbox._server.workspace_manager.Sandbox"),
            patch("harnessbox._server.workspace_manager.AgentManager"),
        ):
            with pytest.raises(ValueError, match="E2B API key not found"):
                await mgr._connect_sandbox("w-nokey")

    @pytest.mark.asyncio
    async def test_connect_populates_workspace_configs(self):
        """_connect_sandbox should store WorkspaceConfig for subsequent snapshot recovery."""
        from harnessbox._server._storage.memory import MemoryBackend
        from harnessbox._server.workspace_manager import WorkspaceInstance

        storage = MemoryBackend()
        await storage.initialize()
        mgr = await WorkspaceManager.create(storage=storage, auto_pause=False)

        now = datetime.now(timezone.utc).isoformat()
        await storage.save_workspace(
            {
                "workspace_id": "w-cfg",
                "remote": "",
                "branch": "",
                "provider": "e2b",
                "provider_sandbox_id": "sb-cfg",
                "snapshot_id": None,
                "harness": "claude-code",
                "runtime_state": RuntimeState.PAUSED.value,
                "workflow_state": "in_progress",
                "created_at": now,
                "last_active": now,
                "config_json": '{"timeout": 600, "session_timeout": 3600, "env_var_keys": ["MY_KEY"]}',
            }
        )

        info = WorkspaceInstance(
            workspace_id="w-cfg",
            remote="",
            branch="",
            provider="e2b",
            provider_sandbox_id="sb-cfg",
            snapshot_id=None,
            runtime_state=RuntimeState.PAUSED.value,
            workflow_state="in_progress",
            created_at=now,
            last_active=now,
            harness="claude-code",
            sandbox_conn=None,
            agent_manager=None,
        )
        mgr._workspaces["w-cfg"] = info

        with (
            patch("harnessbox._server.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox._server.workspace_manager.AgentManager"),
            patch.object(WorkspaceManager, "_resolve_provider_api_key", return_value="fake-key"),
            patch.dict("os.environ", {"MY_KEY": "val"}),
        ):
            mock_sandbox = MockSandbox.return_value
            mock_sandbox.resume = AsyncMock()
            mock_sandbox.sandbox_id = "sb-cfg"
            mock_sandbox.event_buffer.hydrate = AsyncMock()

            await mgr._connect_sandbox("w-cfg")

        config = mgr._workspace_configs.get("w-cfg")
        assert config is not None
        assert config.timeout == 600
        assert config.session_timeout == 3600
        assert config.env_vars == {"MY_KEY": "val"}

    @pytest.mark.asyncio
    async def test_prompt_connects_sandbox_lazily(self):
        """prompt() should connect sandbox and forward message end-to-end."""
        from harnessbox._server._storage.memory import MemoryBackend
        from harnessbox._server.workspace_manager import WorkspaceInstance
        from harnessbox.streaming import EventType as StreamEventType
        from harnessbox.streaming import UniversalEvent

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
                "runtime_state": RuntimeState.PAUSED.value,
                "workflow_state": "in_progress",
                "created_at": now,
                "last_active": now,
                "config_json": '{"timeout": 300, "skip_permissions": true}',
            }
        )

        info = WorkspaceInstance(
            workspace_id="w-prompt",
            remote="https://github.com/user/repo.git",
            branch="main",
            provider="e2b",
            provider_sandbox_id="prompt-sandbox",
            snapshot_id=None,
            runtime_state=RuntimeState.PAUSED.value,
            workflow_state="in_progress",
            created_at=now,
            last_active=now,
            harness="claude-code",
            sandbox_conn=None,
            agent_manager=None,
        )
        mgr._workspaces["w-prompt"] = info

        # Mock agent event stream
        turn_end_event = UniversalEvent(
            event_id="ev-end",
            sequence=1,
            timestamp=now,
            session_id="conv-1",
            event_type=StreamEventType.TURN_ENDED,
            duration_ms=100,
        )

        async def mock_send_message(conv_id, prompt_text, harness="claude-code", **kwargs):
            yield turn_end_event

        with (
            patch("harnessbox._server.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox._server.workspace_manager.AgentManager") as MockAgentMgr,
            patch.object(WorkspaceManager, "_resolve_provider_api_key", return_value="fake-key"),
        ):
            mock_sandbox = MockSandbox.return_value
            mock_sandbox.resume = AsyncMock()
            mock_sandbox.sandbox_id = "prompt-sandbox"
            mock_sandbox._event_buffer = None
            mock_sandbox._cwd = "/workspace"
            mock_sandbox.event_buffer.hydrate = AsyncMock()

            mock_agent = MockAgentMgr.return_value
            mock_agent.send_message = mock_send_message

            # Call prompt() end-to-end — should connect sandbox then stream events
            events = []
            async for event in mgr.prompt("w-prompt", "Hello"):
                events.append(event)

        assert info.sandbox_conn is not None
        assert info.agent_manager is not None
        assert info.runtime_state == RuntimeState.ACTIVE.value
        # First event is USER_PROMPT, last is from agent
        assert events[0].event_type == StreamEventType.USER_PROMPT
        assert events[-1].event_type == StreamEventType.TURN_ENDED
        mock_sandbox.resume.assert_called_once_with("prompt-sandbox")


class TestPerConversationHarness:
    """Per-conversation harness: workspace_manager.prompt() passes harness to agent_manager."""

    @pytest.mark.asyncio
    async def test_prompt_passes_harness_to_agent_manager(self) -> None:
        """The harness kwarg in prompt() reaches agent_manager.send_message()."""

        from harnessbox.events import EventBuffer
        from harnessbox.streaming import EventType, UniversalEvent

        mgr = WorkspaceManager()
        config = WorkspaceConfig()

        with (
            patch("harnessbox._server.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox._server.workspace_manager.AgentManager") as MockAgentMgr,
        ):
            sandbox_instance = MockSandbox.return_value
            sandbox_instance.setup = AsyncMock()
            sandbox_instance.sandbox_id = "sb-1"
            sandbox_instance._skip_permissions = False
            sandbox_instance._cwd = "/workspace"
            sandbox_instance._event_buffer = EventBuffer()

            agent_mgr_instance = MockAgentMgr.return_value

            turn_event = UniversalEvent(
                event_id="e1",
                sequence=1,
                timestamp="2026-01-01T00:00:00Z",
                session_id="conv-1",
                event_type=EventType.TURN_ENDED,
            )

            received_harness = []

            async def fake_send_message(conv_id, prompt, harness="claude-code", **kwargs):
                received_harness.append(harness)
                yield turn_event

            agent_mgr_instance.send_message = fake_send_message

            info = await mgr.create_workspace(config, workspace_id="ws-1")
            info.runtime_state = RuntimeState.ACTIVE.value

            events = []
            async for event in mgr.prompt("ws-1", "hello", harness="codex"):
                events.append(event)

        assert received_harness == ["codex"]

    @pytest.mark.asyncio
    async def test_resume_loads_stored_harness(self) -> None:
        """When resuming a conversation from storage, agent_type is read and used."""
        from harnessbox._server._storage.memory import MemoryBackend
        from harnessbox.events import EventBuffer
        from harnessbox.streaming import EventType, UniversalEvent

        storage = MemoryBackend()
        await storage.initialize()

        mgr = WorkspaceManager(storage=storage)
        config = WorkspaceConfig()

        with (
            patch("harnessbox._server.workspace_manager.Sandbox") as MockSandbox,
            patch("harnessbox._server.workspace_manager.AgentManager") as MockAgentMgr,
        ):
            sandbox_instance = MockSandbox.return_value
            sandbox_instance.setup = AsyncMock()
            sandbox_instance.sandbox_id = "sb-1"
            sandbox_instance._skip_permissions = False
            sandbox_instance._cwd = "/workspace"
            sandbox_instance._event_buffer = EventBuffer()

            agent_mgr_instance = MockAgentMgr.return_value

            turn_event = UniversalEvent(
                event_id="e1",
                sequence=1,
                timestamp="2026-01-01T00:00:00Z",
                session_id="conv-stored",
                event_type=EventType.TURN_ENDED,
            )

            received_harness = []

            async def capture_send_message(conv_id, prompt, harness="claude-code", **kwargs):
                received_harness.append(harness)
                yield turn_event

            agent_mgr_instance.send_message = capture_send_message

            info = await mgr.create_workspace(config, workspace_id="ws-1")
            info.runtime_state = RuntimeState.ACTIVE.value

            await storage.save_conversation(
                {
                    "conversation_id": "conv-stored",
                    "workspace_id": "ws-1",
                    "agent_type": "codex",
                    "title": "test",
                    "last_active": datetime.now(timezone.utc).isoformat(),
                }
            )

            events = []
            async for event in mgr.prompt("ws-1", "hello", harness="claude-code"):
                events.append(event)

        assert received_harness == ["codex"]
