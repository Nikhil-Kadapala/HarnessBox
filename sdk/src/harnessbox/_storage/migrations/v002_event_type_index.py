"""v002: Add index on (workspace_id, event_type) for cost history queries."""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_workspace_type
        ON events(workspace_id, event_type)
    """)
