"""SQLite storage backend for persistent sessions (OSS).

Uses asyncio.to_thread() to wrap synchronous sqlite3 operations. No external
dependencies — sqlite3 is in Python's stdlib.

Events are batched and flushed periodically (50 events or 5 seconds) to
reduce write amplification.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SQLiteBackend:
    """SQLite storage backend with batched event persistence.

    Args:
        path: Database file path. Defaults to ~/.harnessbox/sessions.db.
              Parent directories are created automatically.
        batch_size: Maximum events to buffer before flushing (default: 50).
        batch_interval: Maximum seconds between flushes (default: 5.0).
    """

    def __init__(
        self,
        path: str | Path | None = None,
        batch_size: int = 50,
        batch_interval: float = 5.0,
    ) -> None:
        if path is None:
            path = Path.home() / ".harnessbox" / "sessions.db"
        self.path = Path(path).expanduser().resolve()
        self.batch_size = batch_size
        self.batch_interval = batch_interval

        self._conn: sqlite3.Connection | None = None
        self._pending_events: list[tuple[str, dict[str, Any]]] = []  # (session_id, event)
        self._flush_task: asyncio.Task[None] | None = None
        self._closed = False

    async def initialize(self) -> None:
        """Create database file and tables. Idempotent."""
        # Ensure parent directory exists
        self.path.parent.mkdir(parents=True, exist_ok=True)

        # Open connection in thread (sqlite3 requires same-thread access)
        self._conn = await asyncio.to_thread(self._open_connection)

        # Create schema
        await asyncio.to_thread(self._create_schema, self._conn)

        # Start background flush task
        self._flush_task = asyncio.create_task(self._run_flush_task())

        logger.info(f"SQLite storage initialized at {self.path}")

    def _open_connection(self) -> sqlite3.Connection:
        """Open SQLite connection with WAL mode for concurrent reads."""
        conn = sqlite3.connect(str(self.path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row  # Access columns by name
        return conn

    def _create_schema(self, conn: sqlite3.Connection) -> None:
        """Create tables and indexes. Idempotent."""
        # Workspaces table (replaces sessions)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS workspaces (
                workspace_id        TEXT PRIMARY KEY,
                remote              TEXT NOT NULL,
                branch              TEXT NOT NULL,
                provider            TEXT NOT NULL,
                provider_sandbox_id TEXT,
                snapshot_id         TEXT,
                harness             TEXT NOT NULL,
                status              TEXT NOT NULL DEFAULT 'active',
                created_at          TEXT NOT NULL,
                last_active         TEXT NOT NULL,
                config_json         TEXT NOT NULL,
                workspace_name      TEXT,
                base_branch         TEXT,
                pr_url              TEXT,
                pr_number           INTEGER,
                ci_status           TEXT,
                total_cost_usd      REAL DEFAULT 0.0,
                UNIQUE (remote, branch)
            )
        """)

        # Index for list_workspaces(status, ORDER BY last_active)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_workspaces_status_active
            ON workspaces(status, last_active)
        """)

        # Index for get_or_create_workspace(remote, branch) lookups
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_workspaces_remote
            ON workspaces(remote)
        """)

        # Index for provider operations
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_workspaces_provider
            ON workspaces(provider, provider_sandbox_id)
        """)

        # Conversations table (lightweight index for UI)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                conversation_id TEXT PRIMARY KEY,
                workspace_id    TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
                agent_type      TEXT NOT NULL,
                title           TEXT,
                last_active     TEXT NOT NULL,
                INDEX (workspace_id)
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversations_workspace
            ON conversations(workspace_id)
        """)

        # Events table (for SSE replay, references workspaces not sessions)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                event_id       TEXT PRIMARY KEY,
                workspace_id   TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
                sequence       INTEGER NOT NULL,
                timestamp      TEXT NOT NULL,
                event_type     TEXT NOT NULL,
                event_json     TEXT NOT NULL
            )
        """)

        # Unique index enforces per-workspace monotonic sequence + query performance
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_events_workspace_seq
            ON events(workspace_id, sequence)
        """)

        conn.commit()

    # -- Workspace CRUD --

    async def save_workspace(self, workspace_record: dict[str, Any]) -> None:
        """Save a new workspace record."""
        await asyncio.to_thread(self._save_workspace_sync, workspace_record)

    def _save_workspace_sync(self, record: dict[str, Any]) -> None:
        """Synchronous implementation for asyncio.to_thread()."""
        if self._conn is None:
            raise RuntimeError("SQLiteBackend not initialized")

        try:
            self._conn.execute(
                """
                INSERT INTO workspaces (
                    workspace_id, remote, branch, provider, provider_sandbox_id,
                    snapshot_id, harness, status, created_at, last_active,
                    config_json, workspace_name, base_branch,
                    pr_url, pr_number, ci_status, total_cost_usd
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["workspace_id"],
                    record.get("remote", ""),
                    record.get("branch", ""),
                    record["provider"],
                    record.get("provider_sandbox_id"),
                    record.get("snapshot_id"),
                    record["harness"],
                    record["status"],
                    record["created_at"],
                    record.get("last_active", record["created_at"]),
                    record["config_json"],
                    record.get("workspace_name"),
                    record.get("base_branch"),
                    record.get("pr_url"),
                    record.get("pr_number"),
                    record.get("ci_status"),
                    record.get("total_cost_usd", 0.0),
                ),
            )
            self._conn.commit()
        except sqlite3.IntegrityError as e:
            logger.error(
                f"Duplicate workspace_id or (remote, branch) {record['workspace_id']}: {e}"
            )
            raise KeyError(
                f"Workspace {record['workspace_id']} already exists or (remote, branch) conflict"
            ) from e

    async def get_workspace(self, workspace_id: str) -> dict[str, Any] | None:
        """Retrieve a workspace record by ID."""
        return await asyncio.to_thread(self._get_workspace_sync, workspace_id)

    def _get_workspace_sync(self, workspace_id: str) -> dict[str, Any] | None:
        """Synchronous implementation for asyncio.to_thread()."""
        if self._conn is None:
            raise RuntimeError("SQLiteBackend not initialized")

        cursor = self._conn.execute(
            "SELECT * FROM workspaces WHERE workspace_id = ?", (workspace_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    async def list_workspaces(
        self,
        *,
        status: str | None = None,
        remote: str | None = None,
        branch: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List workspace records with optional filtering and pagination."""
        return await asyncio.to_thread(
            self._list_workspaces_sync, status, remote, branch, limit, offset
        )

    def _list_workspaces_sync(
        self, status: str | None, remote: str | None, branch: str | None, limit: int, offset: int
    ) -> list[dict[str, Any]]:
        """Synchronous implementation for asyncio.to_thread()."""
        if self._conn is None:
            raise RuntimeError("SQLiteBackend not initialized")

        conditions = []
        params: list[Any] = []

        if status is not None:
            conditions.append("status = ?")
            params.append(status)
        if remote is not None:
            conditions.append("remote = ?")
            params.append(remote)
        if branch is not None:
            conditions.append("branch = ?")
            params.append(branch)

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        query = f"""
            SELECT * FROM workspaces
            WHERE {where_clause}
            ORDER BY last_active DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        cursor = self._conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    async def update_workspace(self, workspace_id: str, **fields: Any) -> None:
        """Update specific fields of an existing workspace."""
        await asyncio.to_thread(self._update_workspace_sync, workspace_id, fields)

    def _update_workspace_sync(self, workspace_id: str, fields: dict[str, Any]) -> None:
        """Synchronous implementation for asyncio.to_thread()."""
        if self._conn is None:
            raise RuntimeError("SQLiteBackend not initialized")

        if not fields:
            return

        # Build SET clause dynamically
        set_clause = ", ".join(f"{key} = ?" for key in fields)
        query = f"UPDATE workspaces SET {set_clause} WHERE workspace_id = ?"
        params = tuple(fields.values()) + (workspace_id,)

        cursor = self._conn.execute(query, params)
        self._conn.commit()

        if cursor.rowcount == 0:
            raise KeyError(f"Workspace {workspace_id} not found")

    async def delete_workspace(self, workspace_id: str) -> None:
        """Delete a workspace record and all associated events/conversations (CASCADE)."""
        await asyncio.to_thread(self._delete_workspace_sync, workspace_id)

    def _delete_workspace_sync(self, workspace_id: str) -> None:
        """Synchronous implementation for asyncio.to_thread()."""
        if self._conn is None:
            raise RuntimeError("SQLiteBackend not initialized")

        self._conn.execute("DELETE FROM workspaces WHERE workspace_id = ?", (workspace_id,))
        self._conn.commit()

    # -- Conversation CRUD --

    async def save_conversation(self, conversation_record: dict[str, Any]) -> None:
        """Save a new conversation record."""
        await asyncio.to_thread(self._save_conversation_sync, conversation_record)

    def _save_conversation_sync(self, record: dict[str, Any]) -> None:
        """Synchronous implementation for asyncio.to_thread()."""
        if self._conn is None:
            raise RuntimeError("SQLiteBackend not initialized")

        try:
            self._conn.execute(
                """
                INSERT INTO conversations (
                    conversation_id, workspace_id, agent_type, title, last_active
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    record["conversation_id"],
                    record["workspace_id"],
                    record["agent_type"],
                    record.get("title"),
                    record["last_active"],
                ),
            )
            self._conn.commit()
        except sqlite3.IntegrityError as e:
            logger.error(f"Duplicate conversation_id {record['conversation_id']}: {e}")
            raise KeyError(f"Conversation {record['conversation_id']} already exists") from e

    async def get_conversations(self, workspace_id: str) -> list[dict[str, Any]]:
        """Retrieve all conversations for a workspace."""
        return await asyncio.to_thread(self._get_conversations_sync, workspace_id)

    def _get_conversations_sync(self, workspace_id: str) -> list[dict[str, Any]]:
        """Synchronous implementation for asyncio.to_thread()."""
        if self._conn is None:
            raise RuntimeError("SQLiteBackend not initialized")

        cursor = self._conn.execute(
            """
            SELECT * FROM conversations
            WHERE workspace_id = ?
            ORDER BY last_active DESC
            """,
            (workspace_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    async def update_conversation(self, conversation_id: str, **fields: Any) -> None:
        """Update specific fields of an existing conversation."""
        await asyncio.to_thread(self._update_conversation_sync, conversation_id, fields)

    def _update_conversation_sync(self, conversation_id: str, fields: dict[str, Any]) -> None:
        """Synchronous implementation for asyncio.to_thread()."""
        if self._conn is None:
            raise RuntimeError("SQLiteBackend not initialized")

        if not fields:
            return

        set_clause = ", ".join(f"{key} = ?" for key in fields)
        query = f"UPDATE conversations SET {set_clause} WHERE conversation_id = ?"
        params = tuple(fields.values()) + (conversation_id,)

        cursor = self._conn.execute(query, params)
        self._conn.commit()

        if cursor.rowcount == 0:
            raise KeyError(f"Conversation {conversation_id} not found")

    # -- Legacy Session CRUD (backward compat for existing code) --
    # These methods map to workspace methods for transition period

    async def save_session(self, session_record: dict[str, Any]) -> None:
        """DEPRECATED: Use save_workspace() instead."""
        # Map session_id → workspace_id for backward compat
        workspace_record = {**session_record}
        if "session_id" in workspace_record:
            workspace_record["workspace_id"] = workspace_record.pop("session_id")
        if "updated_at" in workspace_record:
            workspace_record["last_active"] = workspace_record.pop("updated_at")
        # Set defaults for new required fields
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
        # Map updated_at → last_active
        if "updated_at" in fields:
            fields["last_active"] = fields.pop("updated_at")
        await self.update_workspace(session_id, **fields)

    async def delete_session(self, session_id: str) -> None:
        """DEPRECATED: Use delete_workspace() instead."""
        await self.delete_workspace(session_id)

    # -- Event persistence --

    async def append_events(self, workspace_id: str, events: list[dict[str, Any]]) -> None:
        """Append a batch of events (buffered, flushed by background task)."""
        for event in events:
            self._pending_events.append((workspace_id, event))

        # Immediate flush if batch size reached
        if len(self._pending_events) >= self.batch_size:
            await self._flush_events()

    async def _flush_events(self) -> None:
        """Flush pending events to database."""
        if not self._pending_events:
            return

        batch = self._pending_events[:]
        self._pending_events.clear()

        await asyncio.to_thread(self._flush_events_sync, batch)

    def _flush_events_sync(self, batch: list[tuple[str, dict[str, Any]]]) -> None:
        """Synchronous batch insert with duplicate handling."""
        if self._conn is None:
            return

        # Prepare batch insert
        rows = [
            (
                event["event_id"],
                workspace_id,
                event["sequence"],
                event["timestamp"],
                event["event_type"],
                event["event_json"],
            )
            for workspace_id, event in batch
        ]

        try:
            self._conn.executemany(
                """
                INSERT INTO events (event_id, workspace_id, sequence, timestamp, event_type, event_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            self._conn.commit()
        except sqlite3.IntegrityError as e:
            # Duplicate (workspace_id, sequence) — log and skip
            logger.warning(f"Duplicate event in batch (skipped): {e}")
            # Try inserting one by one to identify which are duplicates
            for row in rows:
                try:
                    self._conn.execute(
                        """
                        INSERT INTO events (event_id, workspace_id, sequence, timestamp, event_type, event_json)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        row,
                    )
                except sqlite3.IntegrityError:
                    pass  # Skip duplicate
            self._conn.commit()

    async def _run_flush_task(self) -> None:
        """Background task: flush every batch_interval seconds."""
        try:
            while not self._closed:
                await asyncio.sleep(self.batch_interval)
                await self._flush_events()
        except asyncio.CancelledError:
            # Final flush on cancellation
            await self._flush_events()
            raise

    async def get_events(
        self,
        workspace_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Stream events incrementally (fetch 100, yield, repeat)."""
        offset = 0
        fetch_size = 100

        while True:
            batch = await asyncio.to_thread(
                self._get_events_batch_sync,
                workspace_id,
                after_sequence,
                fetch_size,
                offset,
            )

            if not batch:
                break

            for event in batch:
                yield event

                # Stop if limit reached
                if limit is not None:
                    limit -= 1
                    if limit <= 0:
                        return

            offset += len(batch)

            # If batch < fetch_size, we've reached the end
            if len(batch) < fetch_size:
                break

    def _get_events_batch_sync(
        self,
        workspace_id: str,
        after_sequence: int,
        fetch_size: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        """Fetch a batch of events (synchronous)."""
        if self._conn is None:
            return []

        cursor = self._conn.execute(
            """
            SELECT * FROM events
            WHERE workspace_id = ? AND sequence > ?
            ORDER BY sequence ASC
            LIMIT ? OFFSET ?
            """,
            (workspace_id, after_sequence, fetch_size, offset),
        )
        return [dict(row) for row in cursor.fetchall()]

    async def close(self) -> None:
        """Flush remaining events and close connection."""
        self._closed = True

        # Cancel and wait for flush task
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        # Final flush
        await self._flush_events()

        # Close connection
        if self._conn:
            await asyncio.to_thread(self._conn.close)
            self._conn = None

        logger.info("SQLite storage closed")
