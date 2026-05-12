"""Storage backend protocol for workspace persistence.

Enables workspace state and events to survive server restarts. Supports multiple
backends (memory, SQLite, Supabase) via Protocol-based structural typing.

The storage layer is optional — WorkspaceManager works with storage=None for
pure in-memory workspaces (current behavior). With storage, workspaces persist
across restarts and can be browsed as history.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class StorageBackend(Protocol):
    """Protocol for workspace persistence backends.

    All methods are async. Backends must handle their own initialization
    (table creation, schema setup) in the initialize() method.

    Workspace records are plain dicts (not dataclasses) for flexibility —
    backends can serialize/deserialize as needed without coupling to
    internal data structures.
    """

    async def initialize(self) -> None:
        """Create tables/schema if needed. Idempotent.

        Called once by WorkspaceManager.create() before any other operations.
        Must be safe to call multiple times (CREATE IF NOT EXISTS pattern).
        """
        ...

    # -- Workspace CRUD --

    async def save_workspace(self, workspace_record: dict[str, Any]) -> None:
        """Save a new workspace record.

        Args:
            workspace_record: Workspace metadata dict with keys:
                - workspace_id (str, required)
                - remote (str, required)
                - branch (str, required)
                - provider (str, required)
                - provider_sandbox_id (str | None)
                - snapshot_id (str | None)
                - harness (str, required)
                - status (str, required)
                - created_at (str ISO 8601, required)
                - last_active (str ISO 8601, required)
                - config_json (str, required)
                - workspace_name, base_branch (str | None)
                - pr_url, ci_status (str | None)
                - pr_number (int | None)
                - total_cost_usd (float)

        Raises:
            IntegrityError or equivalent if workspace_id or (remote, branch) already exists.
        """
        ...

    async def get_workspace(self, workspace_id: str) -> dict[str, Any] | None:
        """Retrieve a workspace record by ID.

        Returns:
            Workspace record dict, or None if not found.
        """
        ...

    async def list_workspaces(
        self,
        *,
        status: str | None = None,
        remote: str | None = None,
        branch: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List workspace records with optional filtering and pagination.

        Args:
            status: Filter by status value ('active', 'paused', 'failed', etc.).
            remote: Filter by git remote URL.
            branch: Filter by git branch name.
            limit: Maximum number of records to return.
            offset: Number of records to skip (for pagination).

        Returns:
            List of workspace records, ordered by last_active DESC (most recent first).
        """
        ...

    async def update_workspace(self, workspace_id: str, **fields: Any) -> None:
        """Update specific fields of an existing workspace.

        Args:
            workspace_id: Workspace to update.
            **fields: Key-value pairs of fields to update (status, pr_url, etc.).

        Raises:
            KeyError or equivalent if workspace_id not found.
        """
        ...

    async def delete_workspace(self, workspace_id: str) -> None:
        """Delete a workspace record and all associated events/conversations.

        Args:
            workspace_id: Workspace to delete.

        Note:
            Event and conversation deletion is automatic (CASCADE DELETE).
        """
        ...

    # -- Conversation CRUD --

    async def save_conversation(self, conversation_record: dict[str, Any]) -> None:
        """Save a new conversation record.

        Args:
            conversation_record: Conversation metadata dict with keys:
                - conversation_id (str, required) — Claude's session_id
                - workspace_id (str, required)
                - agent_type (str, required)
                - title (str | None)
                - last_active (str ISO 8601, required)

        Raises:
            IntegrityError or equivalent if conversation_id already exists.
        """
        ...

    async def get_conversations(self, workspace_id: str) -> list[dict[str, Any]]:
        """Retrieve all conversations for a workspace.

        Returns:
            List of conversation records, ordered by last_active DESC.
        """
        ...

    async def update_conversation(self, conversation_id: str, **fields: Any) -> None:
        """Update specific fields of an existing conversation.

        Args:
            conversation_id: Conversation to update.
            **fields: Key-value pairs of fields to update.

        Raises:
            KeyError or equivalent if conversation_id not found.
        """
        ...

    # -- Legacy Session CRUD (for backward compat during transition) --

    async def save_session(self, session_record: dict[str, Any]) -> None:
        """DEPRECATED: Use save_workspace() instead."""
        ...

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        """DEPRECATED: Use get_workspace() instead."""
        ...

    async def list_sessions(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """DEPRECATED: Use list_workspaces() instead."""
        ...

    async def update_session(self, session_id: str, **fields: Any) -> None:
        """DEPRECATED: Use update_workspace() instead."""
        ...

    async def delete_session(self, session_id: str) -> None:
        """DEPRECATED: Use delete_workspace() instead."""
        ...

    # -- Event persistence --

    async def append_events(self, workspace_id: str, events: list[dict[str, Any]]) -> None:
        """Append a batch of events to a workspace's event log.

        Args:
            workspace_id: Workspace these events belong to.
            events: List of event dicts with keys:
                - event_id (str, required)
                - sequence (int, required, per-workspace monotonic)
                - timestamp (str ISO 8601, required)
                - event_type (str, required)
                - event_json (str, required, serialized UniversalEvent)

        Note:
            Duplicate (workspace_id, sequence) pairs should be silently skipped
            (IntegrityError caught and logged). The flush task may retry events.
        """
        ...

    async def get_events(
        self,
        workspace_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Stream events for a workspace, ordered by sequence.

        Args:
            workspace_id: Workspace whose events to retrieve.
            after_sequence: Only return events with sequence > this value.
            limit: Maximum number of events to return (None = unlimited).

        Yields:
            Event dicts in sequence order (oldest first).

        Note:
            Implementations should stream incrementally (fetch 100, yield, repeat)
            to avoid memory spikes for large workspaces.
        """
        ...
        yield {}  # Type hint for AsyncGenerator

    # -- Lifecycle --

    async def close(self) -> None:
        """Flush pending writes and close connections.

        Called during server shutdown. Must ensure all buffered data is written.
        """
        ...
