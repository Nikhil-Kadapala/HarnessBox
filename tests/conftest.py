"""HarnessBox test configuration."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest

from harnessbox.providers import CommandHandle, CommandResult


class MockProvider:
    """In-memory SandboxProvider for testing — no real sandbox created."""

    def __init__(self) -> None:
        self._sandbox_id: str | None = None
        self._running = False
        self._files: dict[str, str] = {}
        self._dirs: list[str] = []
        self._commands: list[str] = []
        self._env_vars: dict[str, str] = {}
        self._stream_lines: list[str] = []
        self._background_pid: int = 42

    @property
    def sandbox_id(self) -> str | None:
        return self._sandbox_id

    @property
    def is_running(self) -> bool:
        return self._running

    async def create(
        self,
        env_vars: dict[str, str] | None = None,
        timeout: int = 300,
    ) -> None:
        self._sandbox_id = "mock-sandbox-123"
        self._running = True
        self._env_vars = dict(env_vars) if env_vars else {}

    async def kill(self) -> None:
        self._running = False
        self._sandbox_id = None

    async def pause(self) -> str:
        if not self._running:
            raise RuntimeError("Not running")
        sid = self._sandbox_id or ""
        self._running = False
        self._sandbox_id = None
        return sid

    async def resume(self, sandbox_id: str) -> None:
        self._sandbox_id = sandbox_id
        self._running = True

    async def write_file(self, path: str, content: str) -> None:
        self._files[path] = content

    async def read_file(self, path: str) -> str:
        if path not in self._files:
            raise FileNotFoundError(path)
        return self._files[path]

    async def make_dir(self, path: str) -> None:
        self._dirs.append(path)

    async def run_command(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int | None = None,
    ) -> CommandResult:
        self._commands.append(command)
        return CommandResult(exit_code=0, stdout="", stderr="")

    async def run_background(
        self,
        command: str,
        cwd: str | None = None,
    ) -> CommandHandle:
        self._commands.append(command)
        return CommandHandle(pid=self._background_pid)

    async def send_stdin(self, pid: int, data: str) -> None:
        self._commands.append(f"stdin:{pid}:{data}")

    async def stream_command(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int | None = None,
    ) -> AsyncGenerator[str, None]:
        self._commands.append(command)
        for line in self._stream_lines:
            yield line


@pytest.fixture
def mock_provider() -> MockProvider:
    """Create a fresh MockProvider instance."""
    return MockProvider()
