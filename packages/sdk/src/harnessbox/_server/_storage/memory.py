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
        # setdefault, not assign: append_events() can run before save_workspace()
        # in the same provisioning flow (e.g. the ACTIVE runtime.state event is
        # emitted just before the workspace record is first saved) — a plain
        # assignment here would silently wipe events already recorded.
        self._conversations.setdefault(workspace_id, [])
        self._events.setdefault(workspace_id, [])

    async def get_workspace(self, workspace_id: str) -> dict[str, Any] | None:
        """Retrieve workspace from memory dict."""
        return self._workspaces.get(workspace_id)

    async def list_workspaces(
        self,
        *,
        runtime_state: str | None = None,
        remote: str | None = None,
        branch: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List workspaces with optional filtering and pagination."""
        workspaces = list(self._workspaces.values())

        if runtime_state is not None:
            workspaces = [w for w in workspaces if w.get("runtime_state") == runtime_state]

        if remote is not None:
            workspaces = [w for w in workspaces if w.get("remote") == remote]

        if branch is not None:
            workspaces = [w for w in workspaces if w.get("branch") == branch]

        workspaces.sort(key=lambda w: w.get("last_active", ""), reverse=True)

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
        """Upsert conversation to memory dict."""
        conversation_id = conversation_record["conversation_id"]
        workspace_id = conversation_record["workspace_id"]

        if workspace_id not in self._conversations:
            self._conversations[workspace_id] = []

        for conv in self._conversations[workspace_id]:
            if conv["conversation_id"] == conversation_id:
                conv["last_active"] = conversation_record["last_active"]
                if conversation_record.get("title"):
                    conv["title"] = conversation_record["title"]
                if conversation_record.get("agent_session_id"):
                    conv["agent_session_id"] = conversation_record["agent_session_id"]
                return

        self._conversations[workspace_id].append(conversation_record.copy())

    async def get_active_conversation(self, workspace_id: str) -> dict[str, Any] | None:
        """Get the most recent conversation for a workspace."""
        conversations = self._conversations.get(workspace_id, [])
        if not conversations:
            return None
        return max(conversations, key=lambda c: c.get("last_active", ""))

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

    async def append_events(self, workspace_id: str, events: list[dict[str, Any]]) -> None:
        """Append events to workspace's event list."""
        if workspace_id not in self._events:
            self._events[workspace_id] = []

        # Check for duplicates (workspace_id, sequence)
        existing_sequences = {e["sequence"] for e in self._events[workspace_id]}
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

    # -- Sequence tracking --

    async def get_max_sequence(self, workspace_id: str) -> int:
        """Return the highest event sequence number for a workspace, or 0."""
        events = self._events.get(workspace_id, [])
        if not events:
            return 0
        return int(max(e.get("sequence", 0) for e in events))

    # -- Cost history --

    async def get_cost_history(
        self, workspace_id: str, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        events = self._events.get(workspace_id, [])
        cost_events = [e for e in events if e.get("event_type") == "cost_update"]
        cost_events.sort(key=lambda e: e.get("sequence", 0), reverse=True)
        return cost_events[:limit]

    # -- Lifecycle --

    async def close(self) -> None:
        """No-op for memory backend."""
        pass
