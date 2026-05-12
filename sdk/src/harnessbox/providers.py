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
    def sandbox_id(self) -> str | None:
        """Return the unique identifier for the running sandbox, or None."""
        ...

    @property
    def is_running(self) -> bool:
        """Return whether the sandbox is currently active."""
        ...

    async def create(
        self,
        env_vars: dict[str, str] | None = None,
        timeout: int = 300,
    ) -> None:
        """Create and start a new sandbox instance."""
        ...

    async def kill(self) -> None:
        """Destroy the sandbox and release all resources."""
        ...

    async def pause(self) -> str:
        """Pause the sandbox and return a snapshot ID for later resumption."""
        ...

    async def resume(self, sandbox_id: str) -> None:
        """Resume a previously paused sandbox from its snapshot ID."""
        ...

    async def create_snapshot(self) -> str:
        """Create a point-in-time snapshot and return its identifier."""
        ...

    async def write_file(self, path: str, content: str) -> None:
        """Write text content to a file in the sandbox."""
        ...

    async def read_file(self, path: str) -> str:
        """Read and return text content from a file in the sandbox."""
        ...

    async def make_dir(self, path: str) -> None:
        """Create a directory (and parents) in the sandbox."""
        ...

    async def run_command(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int | None = None,
    ) -> CommandResult:
        """Run a command synchronously and return exit code, stdout, stderr."""
        ...

    async def run_background(
        self,
        command: str,
        cwd: str | None = None,
    ) -> CommandHandle:
        """Start a background process and return a handle with its PID."""
        ...

    async def send_stdin(self, pid: int, data: str) -> None:
        """Send data to the stdin of a running background process."""
        ...

    def stream_command(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int | None = None,
    ) -> AsyncGenerator[str, None]:
        """Stream stdout lines from a command as an async generator."""
        ...
