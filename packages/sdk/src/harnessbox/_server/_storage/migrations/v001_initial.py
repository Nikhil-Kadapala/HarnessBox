"""v001: Initial schema — workspaces, conversations, events tables."""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS workspaces (
            workspace_id        TEXT PRIMARY KEY,
            remote              TEXT NOT NULL,
            branch              TEXT NOT NULL,
            provider            TEXT NOT NULL,
            provider_sandbox_id TEXT,
            snapshot_id         TEXT,
            harness             TEXT NOT NULL,
            status              TEXT NOT NULL DEFAULT 'active',
            created_at          TEXT NOT NULL,
            last_active         TEXT NOT NULL,
            config_json         TEXT NOT NULL,
            workspace_name      TEXT,
            base_branch         TEXT,
            pr_url              TEXT,
            pr_number           INTEGER,
            ci_status           TEXT,
            total_cost_usd      REAL DEFAULT 0.0,
            UNIQUE (remote, branch)
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_workspaces_status_active
        ON workspaces(status, last_active)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_workspaces_remote
        ON workspaces(remote)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_workspaces_provider
        ON workspaces(provider, provider_sandbox_id)
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            conversation_id TEXT PRIMARY KEY,
            workspace_id    TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
            agent_type      TEXT NOT NULL,
            title           TEXT,
            last_active     TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_conversations_workspace
        ON conversations(workspace_id)
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            event_id       TEXT PRIMARY KEY,
            workspace_id   TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
            sequence       INTEGER NOT NULL,
            timestamp      TEXT NOT NULL,
            event_type     TEXT NOT NULL,
            event_json     TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_events_workspace_seq
        ON events(workspace_id, sequence)
    """)
