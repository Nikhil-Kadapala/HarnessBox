"""Schema migrations for SQLiteBackend.

Each migration is a module with an upgrade(conn) function that receives
a sqlite3.Connection and applies schema changes within a transaction.
"""

from __future__ import annotations

import importlib
import logging
import sqlite3

logger = logging.getLogger(__name__)

MIGRATIONS: list[str] = [
    "harnessbox._storage.migrations.v001_initial",
    "harnessbox._storage.migrations.v002_event_type_index",
]


class MigrationRunner:
    """Runs numbered migrations against a SQLite database.

    Tracks applied version in a `schema_version` table. Each migration
    runs in a transaction; on failure the version stays at the previous value.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._ensure_version_table()

    def _ensure_version_table(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                id      INTEGER PRIMARY KEY CHECK (id = 1),
                version INTEGER NOT NULL DEFAULT 0
            )
        """)
        self._conn.execute("""
            INSERT OR IGNORE INTO schema_version (id, version) VALUES (1, 0)
        """)
        self._conn.commit()

    def get_version(self) -> int:
        cursor = self._conn.execute("SELECT version FROM schema_version WHERE id = 1")
        row = cursor.fetchone()
        return row[0] if row else 0

    def run_pending(self) -> int:
        """Run all migrations newer than current version.

        Returns the number of migrations applied.
        """
        current = self.get_version()
        applied = 0

        for i, module_path in enumerate(MIGRATIONS, start=1):
            if i <= current:
                continue

            module = importlib.import_module(module_path)
            upgrade_fn = getattr(module, "upgrade")

            try:
                upgrade_fn(self._conn)
                self._conn.execute(
                    "UPDATE schema_version SET version = ? WHERE id = 1", (i,)
                )
                self._conn.commit()
                applied += 1
                logger.info(f"Migration v{i:03d} applied: {module_path.rsplit('.', 1)[-1]}")
            except Exception:
                self._conn.rollback()
                logger.exception(f"Migration v{i:03d} failed, rolled back: {module_path}")
                raise

        return applied
