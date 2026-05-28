"""Tests for the SQLite migration runner."""

import sqlite3

import pytest

from harnessbox._server._storage.migrations import MigrationRunner


@pytest.fixture
def conn():
    """In-memory SQLite connection for testing."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    yield c
    c.close()


class TestMigrationRunner:
    def test_initial_version_is_zero(self, conn):
        runner = MigrationRunner(conn)
        assert runner.get_version() == 0

    def test_run_pending_applies_all_migrations(self, conn):
        runner = MigrationRunner(conn)
        applied = runner.run_pending()
        assert applied == 5
        assert runner.get_version() == 5

    def test_run_pending_idempotent(self, conn):
        runner = MigrationRunner(conn)
        runner.run_pending()
        applied = runner.run_pending()
        assert applied == 0
        assert runner.get_version() == 5

    def test_creates_workspaces_table(self, conn):
        runner = MigrationRunner(conn)
        runner.run_pending()
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='workspaces'"
        )
        assert cursor.fetchone() is not None

    def test_creates_conversations_table(self, conn):
        runner = MigrationRunner(conn)
        runner.run_pending()
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='conversations'"
        )
        assert cursor.fetchone() is not None

    def test_creates_events_table(self, conn):
        runner = MigrationRunner(conn)
        runner.run_pending()
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='events'")
        assert cursor.fetchone() is not None

    def test_creates_event_type_index(self, conn):
        runner = MigrationRunner(conn)
        runner.run_pending()
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_events_workspace_type'"
        )
        assert cursor.fetchone() is not None

    def test_rollback_on_failure(self, conn):
        runner = MigrationRunner(conn)
        runner.run_pending()
        assert runner.get_version() == 5

        # Monkey-patch MIGRATIONS to add a failing migration
        from harnessbox._server._storage import migrations

        original = migrations.MIGRATIONS[:]
        migrations.MIGRATIONS.append("harnessbox._server._storage.migrations._fake_broken")

        # Create a fake module that raises during upgrade
        import sys
        import types

        fake_module = types.ModuleType("harnessbox._server._storage.migrations._fake_broken")

        def _failing_upgrade(conn):
            raise RuntimeError("Intentional failure")

        fake_module.upgrade = _failing_upgrade
        sys.modules["harnessbox._server._storage.migrations._fake_broken"] = fake_module

        try:
            with pytest.raises(RuntimeError, match="Intentional failure"):
                runner.run_pending()

            # Version should stay at 5 (fake v006 rolled back)
            assert runner.get_version() == 5
        finally:
            migrations.MIGRATIONS[:] = original
            del sys.modules["harnessbox._server._storage.migrations._fake_broken"]

    def test_sequential_execution_order(self, conn):
        """Migrations run in order: v001 creates tables, v002 adds index."""
        runner = MigrationRunner(conn)

        # Run only v001
        from harnessbox._server._storage import migrations

        original = migrations.MIGRATIONS[:]
        migrations.MIGRATIONS[:] = [original[0]]

        try:
            runner.run_pending()
            assert runner.get_version() == 1

            # Event type index should NOT exist yet
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_events_workspace_type'"
            )
            assert cursor.fetchone() is None
        finally:
            migrations.MIGRATIONS[:] = original

        # Now run remaining (v002 + v003 + v004 + v005)
        applied = runner.run_pending()
        assert applied == 4
        assert runner.get_version() == 5

        # Index should exist now
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_events_workspace_type'"
        )
        assert cursor.fetchone() is not None


class TestSQLiteBackendIntegration:
    """Integration tests for SQLiteBackend with migration runner."""

    @pytest.fixture
    async def backend(self, tmp_path):
        from harnessbox._server._storage.sqlite import SQLiteBackend

        db_path = tmp_path / "test.db"
        backend = SQLiteBackend(path=db_path, max_events_per_workspace=100)
        await backend.initialize()
        yield backend
        await backend.close()

    async def test_initialize_creates_db(self, backend, tmp_path):
        assert (tmp_path / "test.db").exists()

    async def test_save_and_get_workspace(self, backend):
        record = {
            "workspace_id": "ws-1",
            "remote": "https://github.com/test/repo.git",
            "branch": "main",
            "provider": "e2b",
            "harness": "claude-code",
            "runtime_state": "active",
            "workflow_state": "in_progress",
            "created_at": "2026-01-01T00:00:00Z",
            "last_active": "2026-01-01T00:00:00Z",
            "config_json": "{}",
        }
        await backend.save_workspace(record)
        result = await backend.get_workspace("ws-1")
        assert result is not None
        assert result["workspace_id"] == "ws-1"
        assert result["remote"] == "https://github.com/test/repo.git"

    async def test_event_retention_prunes_excess(self, backend):
        record = {
            "workspace_id": "ws-prune",
            "remote": "https://github.com/test/prune.git",
            "branch": "main",
            "provider": "e2b",
            "harness": "claude-code",
            "runtime_state": "active",
            "workflow_state": "in_progress",
            "created_at": "2026-01-01T00:00:00Z",
            "last_active": "2026-01-01T00:00:00Z",
            "config_json": "{}",
        }
        await backend.save_workspace(record)

        # Insert 150 events (backend.max_events = 100)
        events = [
            {
                "event_id": f"evt-{i}",
                "sequence": i,
                "timestamp": "2026-01-01T00:00:00Z",
                "event_type": "text_delta",
                "event_json": f'{{"seq": {i}}}',
            }
            for i in range(150)
        ]
        await backend.append_events("ws-prune", events)

        # Count events in DB (writes are immediate, no flush needed)
        cursor = backend._conn.execute(
            "SELECT COUNT(*) FROM events WHERE workspace_id = ?", ("ws-prune",)
        )
        count = cursor.fetchone()[0]
        assert count == 100

    async def test_get_cost_history(self, backend):
        record = {
            "workspace_id": "ws-cost",
            "remote": "https://github.com/test/cost.git",
            "branch": "main",
            "provider": "e2b",
            "harness": "claude-code",
            "runtime_state": "active",
            "workflow_state": "in_progress",
            "created_at": "2026-01-01T00:00:00Z",
            "last_active": "2026-01-01T00:00:00Z",
            "config_json": "{}",
        }
        await backend.save_workspace(record)

        events = [
            {
                "event_id": f"cost-{i}",
                "sequence": i,
                "timestamp": "2026-01-01T00:00:00Z",
                "event_type": "cost.update",
                "event_json": f'{{"cost_usd": {0.01 * i}}}',
            }
            for i in range(5)
        ]
        # Mix in a non-cost event
        events.append(
            {
                "event_id": "text-1",
                "sequence": 5,
                "timestamp": "2026-01-01T00:00:00Z",
                "event_type": "text_delta",
                "event_json": '{"text": "hello"}',
            }
        )
        await backend.append_events("ws-cost", events)

        history = await backend.get_cost_history("ws-cost", limit=10)
        assert len(history) == 5
        # Most recent first (highest sequence)
        assert history[0]["event_json"] == '{"cost_usd": 0.04}'

    async def test_concurrent_writes_dont_corrupt(self, backend):
        """Verify asyncio.Lock prevents corruption under concurrent appends."""
        import asyncio

        record = {
            "workspace_id": "ws-concurrent",
            "remote": "https://github.com/test/concurrent.git",
            "branch": "main",
            "provider": "e2b",
            "harness": "claude-code",
            "runtime_state": "active",
            "workflow_state": "in_progress",
            "created_at": "2026-01-01T00:00:00Z",
            "last_active": "2026-01-01T00:00:00Z",
            "config_json": "{}",
        }
        await backend.save_workspace(record)

        async def append_batch(start: int) -> None:
            events = [
                {
                    "event_id": f"evt-{start + i}",
                    "sequence": start + i,
                    "timestamp": "2026-01-01T00:00:00Z",
                    "event_type": "text_delta",
                    "event_json": f'{{"n": {start + i}}}',
                }
                for i in range(10)
            ]
            await backend.append_events("ws-concurrent", events)

        # Run 5 concurrent append batches
        await asyncio.gather(*[append_batch(i * 10) for i in range(5)])

        cursor = backend._conn.execute(
            "SELECT COUNT(*) FROM events WHERE workspace_id = ?", ("ws-concurrent",)
        )
        count = cursor.fetchone()[0]
        assert count == 50
