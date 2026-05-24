"""v005: Add agent_session_id to conversations for session recovery."""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute(
        "ALTER TABLE conversations ADD COLUMN agent_session_id TEXT"
    )
