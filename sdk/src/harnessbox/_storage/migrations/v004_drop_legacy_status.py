"""v004: Drop legacy status column (superseded by runtime_state + workflow_state)."""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute("DROP INDEX IF EXISTS idx_workspaces_status_active")
    conn.execute("ALTER TABLE workspaces DROP COLUMN status")
