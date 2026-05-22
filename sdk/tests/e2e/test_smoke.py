"""E2E smoke tests — validate critical paths against real E2B infrastructure."""

from __future__ import annotations

import pytest

from tests.e2e.conftest import TEST_FIXTURE_REPO


@pytest.mark.e2e
class TestE2BSmoke:
    """Smoke tests that provision real E2B sandboxes."""

    async def test_create_and_kill(self, e2b_provider) -> None:
        """Sandbox provisions with a real sandbox_id and kills cleanly."""
        assert e2b_provider.sandbox_id is not None
        assert isinstance(e2b_provider.sandbox_id, str)
        assert len(e2b_provider.sandbox_id) > 0
        assert e2b_provider.is_running is True

        await e2b_provider.kill()
        assert e2b_provider.is_running is False

    async def test_file_roundtrip(self, e2b_provider) -> None:
        """Write a file, read it back, content matches."""
        content = "harnessbox e2e test content\n"
        await e2b_provider.write_file("/tmp/e2e_test.txt", content)
        result = await e2b_provider.read_file("/tmp/e2e_test.txt")
        assert result == content

    async def test_run_command(self, e2b_provider) -> None:
        """Execute a command and get real stdout."""
        result = await e2b_provider.run_command("echo hello-e2e")
        assert result.exit_code == 0
        assert "hello-e2e" in result.stdout

    async def test_git_clone_and_status(self, e2b_provider) -> None:
        """Clone the test fixture repo and verify git status."""
        await e2b_provider.git_clone(
            TEST_FIXTURE_REPO,
            "/home/user/fixture",
            branch="main",
        )
        status = await e2b_provider.git_status("/home/user/fixture")
        assert status.branch == "main"
        assert status.dirty is False

    async def test_pause_and_resume(self, e2b_provider) -> None:
        """Pause sandbox, resume, verify still functional."""
        sandbox_id = await e2b_provider.pause()
        assert isinstance(sandbox_id, str)
        assert len(sandbox_id) > 0
        assert e2b_provider.is_running is False

        await e2b_provider.resume(sandbox_id)
        assert e2b_provider.is_running is True

        result = await e2b_provider.run_command("echo resumed")
        assert result.exit_code == 0
        assert "resumed" in result.stdout
