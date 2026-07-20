"""E2E lifecycle test — full WorkspaceManager stack against real E2B + Claude Code.

Unlike test_smoke.py (which drives E2BProvider directly), these tests go
through WorkspaceManager exactly as the HTTP server does: create_workspace,
prompt, pause_workspace, resume_workspace, prompt again. A second scenario
simulates a server restart — a fresh WorkspaceManager backed by the same
SQLite file reloads the paused workspace from storage and resumes it,
proving snapshot_id/provider_sandbox_id actually round-trip through
persistence rather than relying on in-memory state.

Requires E2B_API_KEY (sandbox provisioning) and ANTHROPIC_API_KEY (Claude
Code auth inside the sandbox) as real, live credentials — each run
provisions a real E2B sandbox and makes real Anthropic API calls. Skipped
automatically when either is absent (see tests/e2e/conftest.py for the
E2B_API_KEY skip; ANTHROPIC_API_KEY is guarded below since prompt() needs
both).
"""

from __future__ import annotations

import asyncio
import os

import pytest

from harnessbox._server._storage.sqlite import SQLiteBackend
from harnessbox._server.registry import WorkspaceConfig
from harnessbox._server.workspace_factory import inject_host_env_vars
from harnessbox._server.workspace_manager import WorkspaceManager
from harnessbox.streaming import EventType as StreamEventType
from harnessbox.streaming import UniversalEvent
from harnessbox.workspace import GitRepoConfig
from tests.e2e.conftest import TEST_FIXTURE_REPO

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not os.environ.get("ANTHROPIC_API_KEY", "").strip(),
        reason="ANTHROPIC_API_KEY not set — required for prompt() to run the claude CLI",
    ),
]

# Real claude CLI turns (provisioning + model latency + tool calls) can take
# a couple of minutes; fail loudly instead of hanging the suite forever.
PROMPT_TIMEOUT = 300


def _make_workspace_config() -> WorkspaceConfig:
    env_vars: dict[str, str] = {}
    inject_host_env_vars(env_vars)
    return WorkspaceConfig(
        provider="e2b",
        api_key=os.environ.get("E2B_API_KEY", "").strip(),
        harness="claude-code",
        workspace=GitRepoConfig(remote=TEST_FIXTURE_REPO, branch="main"),
        env_vars=env_vars,
        skip_permissions=True,
        timeout=120,
    )


async def _drive_prompt_to_completion(
    manager: WorkspaceManager, workspace_id: str, prompt: str
) -> tuple[list[UniversalEvent], bool]:
    """Consume manager.prompt()'s event stream until turn.ended, with a hard timeout."""
    events: list[UniversalEvent] = []
    turn_ended = False

    async def _drive() -> None:
        nonlocal turn_ended
        async for event in manager.prompt(workspace_id, prompt):
            events.append(event)
            if event.event_type in (StreamEventType.TURN_ENDED, StreamEventType.SESSION_ENDED):
                turn_ended = True

    await asyncio.wait_for(_drive(), timeout=PROMPT_TIMEOUT)
    return events, turn_ended


class TestWorkspaceLifecycleE2E:
    """create -> prompt -> pause -> resume -> prompt, all through WorkspaceManager."""

    async def test_create_prompt_pause_resume_prompt(self, tmp_path):
        storage = SQLiteBackend(tmp_path / "sessions.db")
        manager = await WorkspaceManager.create(storage=storage, auto_pause=False)

        info = await manager.create_workspace(_make_workspace_config())
        workspace_id = info.workspace_id
        assert info.runtime_state == "active"
        assert info.provider_sandbox_id

        try:
            events1, ended1 = await _drive_prompt_to_completion(
                manager,
                workspace_id,
                "Create a file named e2e_marker.txt in the current directory containing "
                "exactly the text HARNESSBOX_E2E_OK and nothing else.",
            )
            assert ended1, "first turn never emitted turn.ended"
            assert any(e.event_type == StreamEventType.ITEM_COMPLETED for e in events1)

            # Ground truth: check the sandbox filesystem, not just the chat transcript.
            result = await info.sandbox_conn.run_command("cat e2e_marker.txt")
            assert result.exit_code == 0
            assert "HARNESSBOX_E2E_OK" in result.stdout

            await manager.pause_workspace(workspace_id)
            paused = manager.get_workspace(workspace_id)
            assert paused.runtime_state == "paused"
            assert paused.snapshot_id, "pause must produce a snapshot_id for recovery"

            await manager.resume_workspace(workspace_id)
            resumed = manager.get_workspace(workspace_id)
            assert resumed.runtime_state == "active"
            assert resumed.sandbox_conn is not None

            events2, ended2 = await _drive_prompt_to_completion(
                manager,
                workspace_id,
                "Append a new line containing exactly HARNESSBOX_E2E_TURN2 to e2e_marker.txt.",
            )
            assert ended2, "second turn (post-resume) never emitted turn.ended"

            result2 = await resumed.sandbox_conn.run_command("cat e2e_marker.txt")
            assert result2.exit_code == 0
            assert "HARNESSBOX_E2E_OK" in result2.stdout
            assert "HARNESSBOX_E2E_TURN2" in result2.stdout
        finally:
            await manager.destroy_workspace(workspace_id)


class TestSnapshotRecoveryAcrossRestartE2E:
    """Pause with one WorkspaceManager, resume from a fresh one (simulated restart)."""

    async def test_resume_from_fresh_manager_after_restart(self, tmp_path):
        db_path = tmp_path / "sessions.db"

        storage_a = SQLiteBackend(db_path)
        manager_a = await WorkspaceManager.create(storage=storage_a, auto_pause=False)
        info = await manager_a.create_workspace(_make_workspace_config())
        workspace_id = info.workspace_id

        # Tracks whichever manager currently owns the live sandbox connection,
        # so the finally block destroys through the right one no matter where
        # a mid-test failure happens — a real E2B sandbox left running is a
        # billable leak, not just a dangling test fixture.
        owner = manager_a
        try:
            _, ended = await _drive_prompt_to_completion(
                manager_a,
                workspace_id,
                "Create a file named restart_marker.txt in the current directory "
                "containing exactly the text HARNESSBOX_RESTART_OK.",
            )
            assert ended

            await manager_a.pause_workspace(workspace_id)
            paused = manager_a.get_workspace(workspace_id)
            assert paused.snapshot_id
            assert paused.provider_sandbox_id
            owner = None  # sandbox is paused, no manager holds a live connection

            # Simulate a server restart: close manager_a's storage connection
            # entirely, then build a brand-new WorkspaceManager + SQLiteBackend
            # pointed at the same file. No in-memory state carries over —
            # manager_b only knows what's on disk.
            await storage_a.close()

            storage_b = SQLiteBackend(db_path)
            manager_b = await WorkspaceManager.create(storage=storage_b, auto_pause=False)

            reloaded = manager_b.get_workspace(workspace_id)
            assert reloaded.runtime_state == "paused"
            assert reloaded.snapshot_id == paused.snapshot_id
            assert reloaded.provider_sandbox_id == paused.provider_sandbox_id
            assert reloaded.sandbox_conn is None, "reload must not carry a live connection"

            await manager_b.resume_workspace(workspace_id)
            owner = manager_b
            resumed = manager_b.get_workspace(workspace_id)
            assert resumed.runtime_state == "active"
            assert resumed.sandbox_conn is not None

            result = await resumed.sandbox_conn.run_command("cat restart_marker.txt")
            assert result.exit_code == 0
            assert "HARNESSBOX_RESTART_OK" in result.stdout

            _, ended2 = await _drive_prompt_to_completion(
                manager_b,
                workspace_id,
                "Append a new line containing exactly HARNESSBOX_RESTART_TURN2 to "
                "restart_marker.txt.",
            )
            assert ended2

            result2 = await resumed.sandbox_conn.run_command("cat restart_marker.txt")
            assert "HARNESSBOX_RESTART_OK" in result2.stdout
            assert "HARNESSBOX_RESTART_TURN2" in result2.stdout
        finally:
            if owner is not None:
                await owner.destroy_workspace(workspace_id)
