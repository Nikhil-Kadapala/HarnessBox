"""Provider protocol for sandbox backends (E2B, Docker, Daytona, EC2)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any, Callable, Protocol, runtime_checkable


class SandboxDeadError(Exception):
    """Raised when the sandbox is no longer reachable (timed out, destroyed, or killed)."""


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
        snapshot_id: str | None = None,
    ) -> None:
        """Create and start a new sandbox instance.

        If snapshot_id is provided, the sandbox is created from a previously
        saved snapshot instead of a template.
        """
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

    async def write_file(self, path: str, content: str | bytes) -> None:
        """Write content to a file in the sandbox."""
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
    """Provider supports first-class git workspace operations.

    The workspace layer uses this capability when available instead of
    shelling out to ``git``. Methods here intentionally match the concrete
    operations needed by ``GitRepoConfig`` so callers don't need ``Any`` or
    provider-specific probing.
    """

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
        """Clone a git repository using the provider's native git API."""
        ...

    async def git_add(self, path: str, *, files: list[str] | None = None) -> None:
        """Stage files in the repository at *path*."""
        ...

    async def git_commit(self, path: str, message: str) -> None:
        """Create a commit in the repository at *path*."""
        ...

    async def git_push(
        self,
        path: str,
        *,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        """Push the repository at *path* to its configured remote."""
        ...

    async def git_status(self, path: str) -> Any:
        """Return structured git status information for the repository at *path*."""
        ...

    async def git_configure_user(self, name: str, email: str, *, path: str | None = None) -> None:
        """Configure git user identity for the repository at *path*."""
        ...


@runtime_checkable
class PTYCapable(Protocol):
    """Provider supports interactive PTY sessions."""

    async def pty_create(self, on_data: Callable[[bytes], None], *, cwd: str | None = None) -> int:
        """Create a PTY with an output callback and return its PID."""
        ...

    async def pty_send(self, pid: int, data: bytes) -> None:
        """Send data to a PTY's stdin."""
        ...
