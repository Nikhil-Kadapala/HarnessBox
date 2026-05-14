"""Provider protocol for sandbox backends (E2B, Docker, Daytona, EC2)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any, Callable, Protocol, runtime_checkable


@dataclass
class CommandResult:
    """Result of a command execution in the sandbox."""

    exit_code: int
    stdout: str
    stderr: str


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

    async def start_session(
        self,
        command: str,
        cwd: str,
        on_stdout: Callable[[Any], None],
    ) -> int:
        """Start a long-lived session process and return its PID.

        The process stays alive across multiple prompt turns. Use
        ``send_stdin(pid, data)`` to write to its stdin. The ``on_stdout``
        callback fires for each line of output.
        """
        ...

    async def send_stdin(self, pid: int, data: str) -> None:
        """Send data to the stdin of a running process."""
        ...

    def stream_command(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int | None = None,
    ) -> AsyncGenerator[str, None]:
        """Stream stdout lines from a command as an async generator."""
        ...


@runtime_checkable
class NativeGitCapable(Protocol):
    """Provider supports native git operations (faster than shell fallback)."""

    async def git_clone(
        self,
        url: str,
        dest: str,
        *,
        branch: str | None = None,
        depth: int | None = None,
        auth_token: str | None = None,
    ) -> None:
        """Clone a git repository using the provider's native git API."""
        ...


@runtime_checkable
class PTYCapable(Protocol):
    """Provider supports interactive PTY sessions."""

    async def pty_create(
        self, on_data: Callable[[bytes], None], *, cwd: str | None = None
    ) -> int:
        """Create a PTY with an output callback and return its PID."""
        ...

    async def pty_send(self, pid: int, data: bytes) -> None:
        """Send data to a PTY's stdin."""
        ...
