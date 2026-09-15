"""v008: Persist non-secret workspace defaults on Projects."""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute(
        "ALTER TABLE projects ADD COLUMN workspace_settings_json TEXT NOT NULL DEFAULT '{}'"
    )
