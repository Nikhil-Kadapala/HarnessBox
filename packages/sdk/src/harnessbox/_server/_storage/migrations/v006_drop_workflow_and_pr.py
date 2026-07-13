"""v006: Drop kanban workflow and PR-tracking columns (Reduce & Rebuild Phase 0)."""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute("ALTER TABLE workspaces DROP COLUMN workflow_state")
    conn.execute("ALTER TABLE workspaces DROP COLUMN pr_url")
    conn.execute("ALTER TABLE workspaces DROP COLUMN pr_number")
    conn.execute("ALTER TABLE workspaces DROP COLUMN ci_status")
