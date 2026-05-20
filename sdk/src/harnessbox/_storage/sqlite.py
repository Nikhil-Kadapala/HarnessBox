"""SQLite storage backend for persistent sessions (OSS).

Uses asyncio.to_thread() to wrap synchronous sqlite3 operations. No external
dependencies — sqlite3 is in Python's stdlib.

EventBuffer is the sole batching authority — it delivers pre-formed batches to
append_events() which writes them directly. A single asyncio.Lock serializes
all writes to prevent corruption.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from harnessbox._storage.migrations import MigrationRunner

logger = logging.getLogger(__name__)

DEFAULT_MAX_EVENTS_PER_WORKSPACE = 10_000


class SQLiteBackend:
    """SQLite storage backend with direct event persistence.

    Args:
        path: Database file path. Defaults to ~/.harnessbox/sessions.db.
              Parent directories are created automatically.
        max_events_per_workspace: Event retention cap per workspace (default: 10000).
    """

    def __init__(
        self,
        path: str | Path | None = None,
        max_events_per_workspace: int = DEFAULT_MAX_EVENTS_PER_WORKSPACE,
    ) -> None:
        if path is None:
            path = Path.home() / ".harnessbox" / "sessions.db"
        self.path = Path(path).expanduser().resolve()
        self.max_events = max_events_per_workspace

        self._conn: sqlite3.Connection | None = None
        self._write_lock = asyncio.Lock()
        self._closed = False

    async def initialize(self) -> None:
        """Create database file and run migrations. Idempotent."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await asyncio.to_thread(self._open_connection)
        await asyncio.to_thread(self._run_migrations, self._conn)
        logger.info(f"SQLite storage initialized at {self.path}")

    def _open_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _run_migrations(conn: sqlite3.Connection) -> None:
        runner = MigrationRunner(conn)
        applied = runner.run_pending()
        if applied:
            logger.info(f"Applied {applied} migration(s), now at v{runner.get_version()}")

    # -- Workspace CRUD --

    async def save_workspace(self, workspace_record: dict[str, Any]) -> None:
        async with self._write_lock:
            await asyncio.to_thread(self._save_workspace_sync, workspace_record)

    def _save_workspace_sync(self, record: dict[str, Any]) -> None:
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
            raise KeyError(
                f"Workspace {record['workspace_id']} already exists or (remote, branch) conflict"
            ) from e

    async def get_workspace(self, workspace_id: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._get_workspace_sync, workspace_id)

    def _get_workspace_sync(self, workspace_id: str) -> dict[str, Any] | None:
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
        return await asyncio.to_thread(
            self._list_workspaces_sync, status, remote, branch, limit, offset
        )

    def _list_workspaces_sync(
        self, status: str | None, remote: str | None, branch: str | None, limit: int, offset: int
    ) -> list[dict[str, Any]]:
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
        async with self._write_lock:
            await asyncio.to_thread(self._update_workspace_sync, workspace_id, fields)

    def _update_workspace_sync(self, workspace_id: str, fields: dict[str, Any]) -> None:
        if self._conn is None:
            raise RuntimeError("SQLiteBackend not initialized")
        if not fields:
            return
        set_clause = ", ".join(f"{key} = ?" for key in fields)
        query = f"UPDATE workspaces SET {set_clause} WHERE workspace_id = ?"
        params = tuple(fields.values()) + (workspace_id,)
        cursor = self._conn.execute(query, params)
        self._conn.commit()
        if cursor.rowcount == 0:
            raise KeyError(f"Workspace {workspace_id} not found")

    async def delete_workspace(self, workspace_id: str) -> None:
        async with self._write_lock:
            await asyncio.to_thread(self._delete_workspace_sync, workspace_id)

    def _delete_workspace_sync(self, workspace_id: str) -> None:
        if self._conn is None:
            raise RuntimeError("SQLiteBackend not initialized")
        self._conn.execute("DELETE FROM workspaces WHERE workspace_id = ?", (workspace_id,))
        self._conn.commit()

    # -- Conversation CRUD --

    async def save_conversation(self, conversation_record: dict[str, Any]) -> None:
        async with self._write_lock:
            await asyncio.to_thread(self._save_conversation_sync, conversation_record)

    def _save_conversation_sync(self, record: dict[str, Any]) -> None:
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
            raise KeyError(f"Conversation {record['conversation_id']} already exists") from e

    async def get_conversations(self, workspace_id: str) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._get_conversations_sync, workspace_id)

    def _get_conversations_sync(self, workspace_id: str) -> list[dict[str, Any]]:
        if self._conn is None:
            raise RuntimeError("SQLiteBackend not initialized")
        cursor = self._conn.execute(
            "SELECT * FROM conversations WHERE workspace_id = ? ORDER BY last_active DESC",
            (workspace_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    async def update_conversation(self, conversation_id: str, **fields: Any) -> None:
        async with self._write_lock:
            await asyncio.to_thread(self._update_conversation_sync, conversation_id, fields)

    def _update_conversation_sync(self, conversation_id: str, fields: dict[str, Any]) -> None:
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

    # -- Event persistence --

    async def append_events(self, workspace_id: str, events: list[dict[str, Any]]) -> None:
        async with self._write_lock:
            await asyncio.to_thread(self._write_events_sync, workspace_id, events)

    def _write_events_sync(self, workspace_id: str, events: list[dict[str, Any]]) -> None:
        if self._conn is None:
            return
        rows = [
            (
                event["event_id"],
                workspace_id,
                event["sequence"],
                event["timestamp"],
                event["event_type"],
                event["event_json"],
            )
            for event in events
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
        except sqlite3.IntegrityError:
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
                    pass
            self._conn.commit()

        self._prune_events_sync(workspace_id)

    def _prune_events_sync(self, workspace_id: str) -> None:
        """Delete oldest events beyond max_events_per_workspace."""
        if self._conn is None:
            return
        cursor = self._conn.execute(
            "SELECT COUNT(*) FROM events WHERE workspace_id = ?", (workspace_id,)
        )
        count = cursor.fetchone()[0]
        if count > self.max_events:
            excess = count - self.max_events
            self._conn.execute(
                """
                DELETE FROM events WHERE event_id IN (
                    SELECT event_id FROM events
                    WHERE workspace_id = ?
                    ORDER BY sequence ASC
                    LIMIT ?
                )
                """,
                (workspace_id, excess),
            )
            self._conn.commit()

    async def get_events(
        self,
        workspace_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        offset = 0
        fetch_size = 100
        while True:
            batch = await asyncio.to_thread(
                self._get_events_batch_sync, workspace_id, after_sequence, fetch_size, offset
            )
            if not batch:
                break
            for event in batch:
                yield event
                if limit is not None:
                    limit -= 1
                    if limit <= 0:
                        return
            offset += len(batch)
            if len(batch) < fetch_size:
                break

    def _get_events_batch_sync(
        self, workspace_id: str, after_sequence: int, fetch_size: int, offset: int
    ) -> list[dict[str, Any]]:
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

    # -- Cost history (queries events table) --

    async def get_cost_history(
        self, workspace_id: str, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._get_cost_history_sync, workspace_id, limit)

    def _get_cost_history_sync(self, workspace_id: str, limit: int) -> list[dict[str, Any]]:
        if self._conn is None:
            return []
        cursor = self._conn.execute(
            """
            SELECT event_json FROM events
            WHERE workspace_id = ? AND event_type = 'cost.update'
            ORDER BY sequence DESC
            LIMIT ?
            """,
            (workspace_id, limit),
        )
        return [dict(row) for row in cursor.fetchall()]

    # -- Lifecycle --

    async def close(self) -> None:
        self._closed = True
        if self._conn:
            await asyncio.to_thread(self._conn.close)
            self._conn = None
        logger.info("SQLite storage closed")
