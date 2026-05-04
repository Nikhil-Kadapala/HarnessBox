"""In-memory storage backend for testing and non-persistent workspaces.

This backend preserves the current behavior (all data lost on restart).
Useful for tests and for users who don't want persistence.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any


class MemoryBackend:
    """In-memory storage backend.

    All data is stored in plain Python dicts. No disk I/O. Data is lost
    when the process exits.
    """

    def __init__(self) -> None:
        self._workspaces: dict[str, dict[str, Any]] = {}
        self._conversations: dict[str, list[dict[str, Any]]] = {}  # workspace_id → conversations
        self._events: dict[str, list[dict[str, Any]]] = {}  # workspace_id → events

    async def initialize(self) -> None:
        """No-op for memory backend."""
        pass

    # -- Workspace CRUD --

    async def save_workspace(self, workspace_record: dict[str, Any]) -> None:
        """Save workspace to memory dict."""
        workspace_id = workspace_record["workspace_id"]
        if workspace_id in self._workspaces:
            raise KeyError(f"Workspace {workspace_id} already exists")

        # Check UNIQUE(remote, branch) constraint
        remote = workspace_record.get("remote", "")
        branch = workspace_record.get("branch", "")
        for ws in self._workspaces.values():
            if ws.get("remote") == remote and ws.get("branch") == branch:
                raise KeyError(f"Workspace with (remote={remote}, branch={branch}) already exists")

        self._workspaces[workspace_id] = workspace_record.copy()
        self._conversations[workspace_id] = []
        self._events[workspace_id] = []

    async def get_workspace(self, workspace_id: str) -> dict[str, Any] | None:
        """Retrieve workspace from memory dict."""
        return self._workspaces.get(workspace_id)

    async def list_workspaces(
        self,
        *,
        status: str | None = None,
        remote: str | None = None,
        branch: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List workspaces with optional filtering and pagination."""
        workspaces = list(self._workspaces.values())

        # Filter by status
        if status is not None:
            workspaces = [w for w in workspaces if w.get("status") == status]

        # Filter by remote
        if remote is not None:
            workspaces = [w for w in workspaces if w.get("remote") == remote]

        # Filter by branch
        if branch is not None:
            workspaces = [w for w in workspaces if w.get("branch") == branch]

        # Sort by last_active DESC (most recent first)
        workspaces.sort(key=lambda w: w.get("last_active", ""), reverse=True)

        # Paginate
        return workspaces[offset : offset + limit]

    async def update_workspace(self, workspace_id: str, **fields: Any) -> None:
        """Update workspace fields."""
        if workspace_id not in self._workspaces:
            raise KeyError(f"Workspace {workspace_id} not found")

        for key, value in fields.items():
            self._workspaces[workspace_id][key] = value

    async def delete_workspace(self, workspace_id: str) -> None:
        """Delete workspace and associated conversations/events."""
        self._workspaces.pop(workspace_id, None)
        self._conversations.pop(workspace_id, None)
        self._events.pop(workspace_id, None)

    # -- Conversation CRUD --

    async def save_conversation(self, conversation_record: dict[str, Any]) -> None:
        """Save conversation to memory dict."""
        conversation_id = conversation_record["conversation_id"]
        workspace_id = conversation_record["workspace_id"]

        if workspace_id not in self._conversations:
            self._conversations[workspace_id] = []

        # Check for duplicate conversation_id
        for conv in self._conversations[workspace_id]:
            if conv["conversation_id"] == conversation_id:
                raise KeyError(f"Conversation {conversation_id} already exists")

        self._conversations[workspace_id].append(conversation_record.copy())

    async def get_conversations(self, workspace_id: str) -> list[dict[str, Any]]:
        """Retrieve all conversations for a workspace."""
        conversations = self._conversations.get(workspace_id, [])
        # Sort by last_active DESC
        return sorted(conversations, key=lambda c: c.get("last_active", ""), reverse=True)

    async def update_conversation(self, conversation_id: str, **fields: Any) -> None:
        """Update conversation fields."""
        # Find conversation across all workspaces
        for workspace_id, convs in self._conversations.items():
            for conv in convs:
                if conv["conversation_id"] == conversation_id:
                    for key, value in fields.items():
                        conv[key] = value
                    return

        raise KeyError(f"Conversation {conversation_id} not found")

    # -- Event persistence --

    async def append_events(
        self, workspace_id: str, events: list[dict[str, Any]]
    ) -> None:
        """Append events to workspace's event list."""
        if workspace_id not in self._events:
            self._events[workspace_id] = []

        # Check for duplicates (workspace_id, sequence)
        existing_sequences = {
            e["sequence"] for e in self._events[workspace_id]
        }
        for event in events:
            if event["sequence"] not in existing_sequences:
                self._events[workspace_id].append(event.copy())

    async def get_events(
        self,
        workspace_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Stream events for a workspace."""
        events = self._events.get(workspace_id, [])

        # Filter and sort
        events = [e for e in events if e["sequence"] > after_sequence]
        events.sort(key=lambda e: e["sequence"])

        # Apply limit
        if limit is not None:
            events = events[:limit]

        for event in events:
            yield event

    # -- Legacy Session CRUD (backward compat) --

    async def save_session(self, session_record: dict[str, Any]) -> None:
        """DEPRECATED: Use save_workspace() instead."""
        workspace_record = {**session_record}
        if "session_id" in workspace_record:
            workspace_record["workspace_id"] = workspace_record.pop("session_id")
        if "updated_at" in workspace_record:
            workspace_record["last_active"] = workspace_record.pop("updated_at")
        workspace_record.setdefault("remote", "")
        workspace_record.setdefault("branch", "")
        workspace_record.setdefault("provider", "e2b")
        await self.save_workspace(workspace_record)

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        """DEPRECATED: Use get_workspace() instead."""
        return await self.get_workspace(session_id)

    async def list_sessions(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """DEPRECATED: Use list_workspaces() instead."""
        return await self.list_workspaces(status=status, limit=limit, offset=offset)

    async def update_session(self, session_id: str, **fields: Any) -> None:
        """DEPRECATED: Use update_workspace() instead."""
        if "updated_at" in fields:
            fields["last_active"] = fields.pop("updated_at")
        await self.update_workspace(session_id, **fields)

    async def delete_session(self, session_id: str) -> None:
        """DEPRECATED: Use delete_workspace() instead."""
        await self.delete_workspace(session_id)

    # -- Lifecycle --

    async def close(self) -> None:
        """No-op for memory backend."""
        pass
