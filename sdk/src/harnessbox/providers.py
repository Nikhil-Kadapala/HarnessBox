"""Provider protocol for sandbox backends (E2B, Docker, Daytona, EC2)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class CommandResult:
    """Result of a command execution in the sandbox."""

    exit_code: int
    stdout: str
    stderr: str


@dataclass
class CommandHandle:
    """Handle for a background process in the sandbox."""

    pid: int


@runtime_checkable
class SandboxProvider(Protocol):
    """Protocol that sandbox backends must implement.

    All methods are async. Providers must be instantiated by the user
    with backend-specific configuration (api_key, template, region, etc.).
    """

    @property
    def sandbox_id(self) -> str | None: ...

    @property
    def is_running(self) -> bool: ...

    async def create(
        self,
        env_vars: dict[str, str] | None = None,
        timeout: int = 300,
    ) -> None: ...

    async def kill(self) -> None: ...

    async def pause(self) -> str: ...

    async def resume(self, sandbox_id: str) -> None: ...

    async def write_file(self, path: str, content: str) -> None: ...

    async def read_file(self, path: str) -> str: ...

    async def make_dir(self, path: str) -> None: ...

    async def run_command(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int | None = None,
    ) -> CommandResult: ...

    async def run_background(
        self,
        command: str,
        cwd: str | None = None,
    ) -> CommandHandle: ...

    async def send_stdin(self, pid: int, data: str) -> None: ...

    def stream_command(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int | None = None,
    ) -> AsyncGenerator[str, None]: ...
