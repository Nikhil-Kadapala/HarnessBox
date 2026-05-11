"""Tests for harnessbox storage backends — workspaces and conversations persistence."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from harnessbox._storage.memory import MemoryBackend
from harnessbox.lifecycle import WorkspaceState


@pytest.fixture
async def memory_backend():
    """MemoryBackend initialized for tests."""
    backend = MemoryBackend()
    await backend.initialize()
    return backend


class TestWorkspaceCRUD:
    """Test workspace CRUD operations."""

    @pytest.mark.asyncio
    async def test_save_workspace(self, memory_backend):
        """Should save workspace to storage."""
        record = {
            "workspace_id": "w-1",
            "remote": "https://github.com/user/repo.git",
            "branch": "main",
            "provider": "e2b",
            "provider_sandbox_id": None,
            "snapshot_id": None,
            "harness": "claude-code",
            "status": WorkspaceState.ACTIVE.value,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_active": datetime.now(timezone.utc).isoformat(),
            "config_json": "{}",
        }

        await memory_backend.save_workspace(record)

        result = await memory_backend.get_workspace("w-1")
        assert result is not None
        assert result["workspace_id"] == "w-1"
        assert result["remote"] == "https://github.com/user/repo.git"

    @pytest.mark.asyncio
    async def test_get_workspace_not_found(self, memory_backend):
        """Should return None for non-existent workspace."""
        result = await memory_backend.get_workspace("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_workspaces(self, memory_backend):
        """Should list all workspaces."""
        await memory_backend.save_workspace(
            {
                "workspace_id": "w-1",
                "remote": "https://github.com/user/repo.git",
                "branch": "main",
                "provider": "e2b",
                "provider_sandbox_id": None,
                "snapshot_id": None,
                "harness": "claude-code",
                "status": WorkspaceState.ACTIVE.value,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_active": datetime.now(timezone.utc).isoformat(),
                "config_json": "{}",
            }
        )
        await memory_backend.save_workspace(
            {
                "workspace_id": "w-2",
                "remote": "https://github.com/user/other.git",
                "branch": "dev",
                "provider": "e2b",
                "provider_sandbox_id": None,
                "snapshot_id": None,
                "harness": "claude-code",
                "status": WorkspaceState.PAUSED.value,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_active": datetime.now(timezone.utc).isoformat(),
                "config_json": "{}",
            }
        )

        result = await memory_backend.list_workspaces()

        assert len(result) == 2
        assert {w["workspace_id"] for w in result} == {"w-1", "w-2"}

    @pytest.mark.asyncio
    async def test_list_workspaces_filter_by_status(self, memory_backend):
        """Should filter workspaces by status."""
        await memory_backend.save_workspace(
            {
                "workspace_id": "w-1",
                "remote": "https://github.com/user/repo.git",
                "branch": "main",
                "provider": "e2b",
                "provider_sandbox_id": None,
                "snapshot_id": None,
                "harness": "claude-code",
                "status": WorkspaceState.ACTIVE.value,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_active": datetime.now(timezone.utc).isoformat(),
                "config_json": "{}",
            }
        )
        await memory_backend.save_workspace(
            {
                "workspace_id": "w-2",
                "remote": "https://github.com/user/other.git",
                "branch": "dev",
                "provider": "e2b",
                "provider_sandbox_id": None,
                "snapshot_id": None,
                "harness": "claude-code",
                "status": WorkspaceState.PAUSED.value,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_active": datetime.now(timezone.utc).isoformat(),
                "config_json": "{}",
            }
        )

        result = await memory_backend.list_workspaces(status=WorkspaceState.PAUSED.value)

        assert len(result) == 1
        assert result[0]["workspace_id"] == "w-2"

    @pytest.mark.asyncio
    async def test_update_workspace(self, memory_backend):
        """Should update workspace fields."""
        await memory_backend.save_workspace(
            {
                "workspace_id": "w-1",
                "remote": "https://github.com/user/repo.git",
                "branch": "main",
                "provider": "e2b",
                "provider_sandbox_id": None,
                "snapshot_id": None,
                "harness": "claude-code",
                "status": WorkspaceState.ACTIVE.value,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_active": datetime.now(timezone.utc).isoformat(),
                "config_json": "{}",
            }
        )

        await memory_backend.update_workspace("w-1", status=WorkspaceState.PAUSED.value)

        result = await memory_backend.get_workspace("w-1")
        assert result["status"] == WorkspaceState.PAUSED.value

    @pytest.mark.asyncio
    async def test_delete_workspace(self, memory_backend):
        """Should delete workspace."""
        await memory_backend.save_workspace(
            {
                "workspace_id": "w-1",
                "remote": "https://github.com/user/repo.git",
                "branch": "main",
                "provider": "e2b",
                "provider_sandbox_id": None,
                "snapshot_id": None,
                "harness": "claude-code",
                "status": WorkspaceState.ACTIVE.value,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_active": datetime.now(timezone.utc).isoformat(),
                "config_json": "{}",
            }
        )

        await memory_backend.delete_workspace("w-1")

        result = await memory_backend.get_workspace("w-1")
        assert result is None


class TestUniqueConstraint:
    """Test UNIQUE(remote, branch) constraint."""

    @pytest.mark.asyncio
    async def test_duplicate_remote_branch_raises(self, memory_backend):
        """Should reject duplicate (remote, branch) combination."""
        await memory_backend.save_workspace(
            {
                "workspace_id": "w-1",
                "remote": "https://github.com/user/repo.git",
                "branch": "main",
                "provider": "e2b",
                "provider_sandbox_id": None,
                "snapshot_id": None,
                "harness": "claude-code",
                "status": WorkspaceState.ACTIVE.value,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_active": datetime.now(timezone.utc).isoformat(),
                "config_json": "{}",
            }
        )

        with pytest.raises(KeyError, match="already exists"):
            await memory_backend.save_workspace(
                {
                    "workspace_id": "w-2",
                    "remote": "https://github.com/user/repo.git",
                    "branch": "main",
                    "provider": "e2b",
                    "provider_sandbox_id": None,
                    "snapshot_id": None,
                    "harness": "claude-code",
                    "status": WorkspaceState.ACTIVE.value,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "last_active": datetime.now(timezone.utc).isoformat(),
                    "config_json": "{}",
                }
            )


class TestConversationCRUD:
    """Test conversation CRUD operations."""

    @pytest.mark.asyncio
    async def test_save_conversation(self, memory_backend):
        """Should save conversation to storage."""
        # Create workspace first
        await memory_backend.save_workspace(
            {
                "workspace_id": "w-1",
                "remote": "https://github.com/user/repo.git",
                "branch": "main",
                "provider": "e2b",
                "provider_sandbox_id": None,
                "snapshot_id": None,
                "harness": "claude-code",
                "status": WorkspaceState.ACTIVE.value,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_active": datetime.now(timezone.utc).isoformat(),
                "config_json": "{}",
            }
        )

        # Save conversation
        await memory_backend.save_conversation(
            {
                "conversation_id": "conv-1",
                "workspace_id": "w-1",
                "agent_type": "claude-code",
                "title": "Test conversation",
                "last_active": datetime.now(timezone.utc).isoformat(),
            }
        )

        result = await memory_backend.get_conversations("w-1")
        assert len(result) == 1
        assert result[0]["conversation_id"] == "conv-1"

    @pytest.mark.asyncio
    async def test_get_conversations_empty(self, memory_backend):
        """Should return empty list for workspace with no conversations."""
        result = await memory_backend.get_conversations("nonexistent")
        assert result == []

    @pytest.mark.asyncio
    async def test_update_conversation(self, memory_backend):
        """Should update conversation fields."""
        await memory_backend.save_workspace(
            {
                "workspace_id": "w-1",
                "remote": "https://github.com/user/repo.git",
                "branch": "main",
                "provider": "e2b",
                "provider_sandbox_id": None,
                "snapshot_id": None,
                "harness": "claude-code",
                "status": WorkspaceState.ACTIVE.value,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_active": datetime.now(timezone.utc).isoformat(),
                "config_json": "{}",
            }
        )
        await memory_backend.save_conversation(
            {
                "conversation_id": "conv-1",
                "workspace_id": "w-1",
                "agent_type": "claude-code",
                "title": "Old title",
                "last_active": datetime.now(timezone.utc).isoformat(),
            }
        )

        await memory_backend.update_conversation("conv-1", title="New title")

        result = await memory_backend.get_conversations("w-1")
        assert result[0]["title"] == "New title"
