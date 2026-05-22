"""Provider contract tests — behavioral guarantees both MockProvider and E2BProvider must satisfy."""

from __future__ import annotations

import pytest

from harnessbox.providers import CommandResult


class TestProviderContract:
    """Behavioral contract that all SandboxProvider implementations must satisfy."""

    async def test_create_sets_sandbox_id(self, provider) -> None:
        """After create(), sandbox_id is a non-empty string."""
        assert provider.sandbox_id is not None
        assert isinstance(provider.sandbox_id, str)
        assert len(provider.sandbox_id) > 0

    async def test_create_sets_running(self, provider) -> None:
        """After create(), is_running is True."""
        assert provider.is_running is True

    async def test_file_write_read_roundtrip(self, provider) -> None:
        """write_file + read_file roundtrips content exactly."""
        content = "contract test content"
        await provider.write_file("/tmp/contract_test.txt", content)
        result = await provider.read_file("/tmp/contract_test.txt")
        assert result == content

    async def test_run_command_returns_result(self, provider) -> None:
        """run_command returns CommandResult with correct exit_code and stdout."""
        result = await provider.run_command("echo contract")
        assert isinstance(result, CommandResult)
        assert result.exit_code == 0
        assert "contract" in result.stdout

    async def test_kill_clears_state(self, provider) -> None:
        """After kill(), sandbox_id is None and is_running is False."""
        await provider.kill()
        assert provider.sandbox_id is None
        assert provider.is_running is False

    async def test_pause_returns_id(self, provider) -> None:
        """pause() returns a non-empty string identifier."""
        result = await provider.pause()
        assert isinstance(result, str)
        assert len(result) > 0
        assert provider.is_running is False

    async def test_make_dir_does_not_raise(self, provider) -> None:
        """make_dir() completes without raising."""
        await provider.make_dir("/tmp/contract_test_dir")

    async def test_read_nonexistent_raises(self, provider) -> None:
        """read_file() on nonexistent path raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            await provider.read_file("/nonexistent/path/that/does/not/exist.txt")
