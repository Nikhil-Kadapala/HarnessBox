"""v003: Split status into runtime_state + workflow_state columns."""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute("ALTER TABLE workspaces ADD COLUMN runtime_state TEXT NOT NULL DEFAULT 'active'")
    conn.execute("ALTER TABLE workspaces ADD COLUMN workflow_state TEXT NOT NULL DEFAULT 'backlog'")

    conn.execute("""
        UPDATE workspaces SET runtime_state = CASE
            WHEN status IN ('starting', 'active', 'paused', 'ending', 'failed') THEN status
            WHEN status = 'backlog' THEN 'ended'
            WHEN status = 'in_review' THEN 'paused'
            WHEN status = 'merged' THEN 'ended'
            WHEN status = 'archived' THEN 'ended'
            ELSE 'failed'
        END
    """)

    conn.execute("""
        UPDATE workspaces SET workflow_state = CASE
            WHEN status = 'backlog' THEN 'backlog'
            WHEN status = 'in_review' THEN 'in_review'
            WHEN status = 'merged' THEN 'merged'
            WHEN status = 'archived' THEN 'archived'
            ELSE 'in_progress'
        END
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_workspaces_runtime_state
        ON workspaces(runtime_state, last_active)
    """)
