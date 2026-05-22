"""HarnessBox test configuration."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest

from harnessbox.providers import CommandResult


class MockProvider:
    """In-memory SandboxProvider for testing — no real sandbox created."""

    def __init__(self) -> None:
        self._sandbox_id: str | None = None
        self._running = False
        self._files: dict[str, str | bytes] = {}
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
        snapshot_id: str | None = None,
    ) -> None:
        self._sandbox_id = f"mock-sandbox-from-{snapshot_id}" if snapshot_id else "mock-sandbox-123"
        self._running = True
        self._env_vars = dict(env_vars) if env_vars else {}
        self._snapshot_id = snapshot_id

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

    async def create_snapshot(self) -> str:
        if not self._running:
            raise RuntimeError("Not running")
        return f"snapshot-{self._sandbox_id}"

    async def write_file(self, path: str, content: str | bytes) -> None:
        self._files[path] = content

    async def read_file(self, path: str) -> str:
        if path not in self._files:
            raise FileNotFoundError(path)
        content = self._files[path]
        return content if isinstance(content, str) else content.decode()

    async def make_dir(self, path: str) -> None:
        self._dirs.append(path)

    async def run_command(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int | None = None,
    ) -> CommandResult:
        self._commands.append(command)
        if command.startswith("echo "):
            return CommandResult(exit_code=0, stdout=command[5:] + "\n", stderr="")
        return CommandResult(exit_code=0, stdout="", stderr="")

    async def start_session(
        self,
        command: str,
        cwd: str,
        on_stdout: Any,
    ) -> int:
        self._commands.append(command)
        self._on_stdout = on_stdout
        if self._stream_lines:
            for line in self._stream_lines:
                on_stdout(type("Data", (), {"line": line})())
        return self._background_pid

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

    # -- NativeGitCapable methods --

    async def git_clone(
        self,
        url: str,
        dest: str,
        *,
        branch: str | None = None,
        depth: int | None = None,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self._commands.append(f"git_clone:{url}:{dest}:branch={branch}:depth={depth}")

    async def git_add(self, path: str, *, files: list[str] | None = None) -> None:
        self._commands.append(f"git_add:{path}:files={files}")

    async def git_commit(self, path: str, message: str) -> None:
        self._commands.append(f"git_commit:{path}:{message}")

    async def git_push(
        self, path: str, *, username: str | None = None, password: str | None = None
    ) -> None:
        self._commands.append(f"git_push:{path}")

    async def git_status(self, path: str) -> Any:
        from harnessbox.workspace import GitStatus

        return GitStatus(branch="main", ahead=0, behind=0, dirty=False)

    async def git_configure_user(self, name: str, email: str, *, path: str | None = None) -> None:
        self._commands.append(f"git_configure_user:{name}:{email}:path={path}")

    async def git_dangerously_authenticate(
        self, username: str, password: str, *, host: str = "github.com"
    ) -> None:
        self._commands.append(f"git_dangerously_authenticate:{username}:host={host}")

    async def git_create_branch(self, path: str, branch: str) -> None:
        self._commands.append(f"git_create_branch:{path}:{branch}")

    async def git_set_config(
        self, key: str, value: str, *, scope: str = "global", path: str | None = None
    ) -> None:
        self._commands.append(f"git_set_config:{key}={value}:scope={scope}:path={path}")


@pytest.fixture
def mock_provider() -> MockProvider:
    """Create a fresh MockProvider instance."""
    return MockProvider()
