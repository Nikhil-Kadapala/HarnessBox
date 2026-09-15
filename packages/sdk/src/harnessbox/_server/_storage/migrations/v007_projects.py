"""v007: Durable Projects and nullable Workspace project references."""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            project_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            remote TEXT NOT NULL,
            default_branch TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "ALTER TABLE workspaces ADD COLUMN project_id TEXT REFERENCES projects(project_id)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_workspaces_project ON workspaces(project_id)")
