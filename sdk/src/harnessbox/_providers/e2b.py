"""E2B sandbox provider — wraps e2b.AsyncSandbox."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator
from typing import Any

from harnessbox.providers import CommandResult, SandboxDeadError

logger = logging.getLogger("harnessbox.e2b")

_DEAD_SANDBOX_SIGNALS = ("sandbox was not found", "502", "unavailable", "timeout")


def _is_sandbox_dead(exc: Exception) -> bool:
    """Check if an E2B exception indicates the sandbox is unreachable."""
    msg = str(exc).lower()
    return any(signal in msg for signal in _DEAD_SANDBOX_SIGNALS)


class E2BProvider:
    """SandboxProvider implementation backed by E2B's AsyncSandbox.

    Requires the ``e2b`` package to be installed separately.
    """

    # Maximum total extensions = 3x the original timeout. Prevents runaway sessions.
    _MAX_EXTENSION_MULTIPLIER = 3

    def __init__(
        self,
        *,
        api_key: str,
        template: str = "base",
        timeout: int = 300,
    ) -> None:
        self._api_key = api_key
        self._template = template
        self._timeout = timeout
        self._sandbox: Any = None
        self._turn_start_time: float | None = None
        self._total_extensions: int = 0  # accumulated extra seconds granted across all turns
        self._extended_this_turn: bool = False  # grant at most one extension per turn

    @staticmethod
    def _get_sdk() -> Any:
        try:
            from e2b import AsyncSandbox

            return AsyncSandbox
        except ImportError:
            raise ImportError(
                "E2B provider requires the 'e2b' package. Install it with: pip install e2b"
            )

    @property
    def sandbox_id(self) -> str | None:
        if self._sandbox is None:
            return None
        sid: str = self._sandbox.sandbox_id
        return sid

    @property
    def is_running(self) -> bool:
        return self._sandbox is not None

    # -- Lifecycle --

    async def create(
        self,
        env_vars: dict[str, str] | None = None,
        timeout: int = 300,
        snapshot_id: str | None = None,
    ) -> None:
        async_sandbox_cls = self._get_sdk()
        source = {"snapshot": snapshot_id} if snapshot_id else {"template": self._template}
        self._sandbox = await async_sandbox_cls.create(
            **source,
            api_key=self._api_key,
            envs=env_vars or {},
            timeout=timeout,
            lifecycle={
                "on_timeout": "pause",
                "auto_resume": True,
            },
        )
        # Reset extension counters — each new sandbox has a fresh TTL budget.
        self._total_extensions = 0
        self._extended_this_turn = False

    async def kill(self) -> None:
        if self._sandbox is None:
            return
        try:
            await self._sandbox.kill()
        except Exception:
            pass
        finally:
            self._sandbox = None

    async def pause(self) -> str:
        if self._sandbox is None:
            raise RuntimeError("Sandbox not running")
        sid: str = self._sandbox.sandbox_id
        await self._sandbox.pause()
        self._sandbox = None
        return sid

    async def resume(self, sandbox_id: str) -> None:
        async_sandbox_cls = self._get_sdk()
        self._sandbox = await async_sandbox_cls.connect(
            sandbox_id,
            api_key=self._api_key,
        )

    async def create_snapshot(self) -> str:
        """Create a snapshot of the sandbox's current filesystem state.

        Returns:
            snapshot_id for later restoration
        """
        if self._sandbox is None:
            raise RuntimeError("Sandbox not running")
        snapshot = await self._sandbox.create_snapshot()
        return snapshot.snapshot_id

    async def set_timeout(self, timeout: int) -> None:
        """Extend the E2B sandbox timeout to at least `timeout` more seconds."""
        if self._sandbox is None:
            raise RuntimeError("Sandbox not running")
        await self._sandbox.set_timeout(timeout)

    def notify_turn_start(self) -> None:
        """Record turn start; resets per-turn extension flag so we extend at most once."""
        self._turn_start_time = time.monotonic()
        self._extended_this_turn = False

    def notify_turn_end(self) -> None:
        """Clear turn tracking so maybe_extend_timeout is a no-op between turns."""
        self._turn_start_time = None
        self._extended_this_turn = False

    async def maybe_extend_timeout(self) -> bool:
        """Extend sandbox timeout proactively if the turn is past the halfway mark.

        Fires at most once per turn (guarded by _extended_this_turn) and caps total
        extra time at (_MAX_EXTENSION_MULTIPLIER - 1) * original timeout across all turns.
        """
        if self._sandbox is None or self._turn_start_time is None:
            return False
        if self._extended_this_turn:
            return False

        elapsed = time.monotonic() - self._turn_start_time
        if elapsed < self._timeout / 2.0:
            return False

        max_extra = (self._MAX_EXTENSION_MULTIPLIER - 1) * self._timeout
        if self._total_extensions >= max_extra:
            logger.warning(
                "E2B timeout extension cap reached (%ds extra already granted)", max_extra
            )
            return False

        extension = min(self._timeout // 2, max_extra - self._total_extensions)

        # E2B set_timeout(N) sets remaining TTL to N from now (not "+N"). Pass the
        # estimated remaining lifetime plus the extension so we don't accidentally
        # shrink the sandbox TTL if called before the halfway point is fully elapsed.
        remaining = max(0, int(self._timeout - elapsed))

        try:
            await self.set_timeout(remaining + extension)
            self._total_extensions += extension
            self._extended_this_turn = True
            logger.info(
                "Extended E2B sandbox timeout by %ds (total extra: %ds / %ds cap)",
                extension,
                self._total_extensions,
                max_extra,
            )
            return True
        except Exception as e:
            logger.warning("Failed to extend E2B sandbox timeout: %s", e)
            return False

    # -- File I/O --

    async def write_file(self, path: str, content: str | bytes) -> None:
        await self._sandbox.files.write(path, content)

    async def read_file(self, path: str) -> str:
        try:
            content: str = await self._sandbox.files.read(path)
        except Exception as e:
            if "does not exist" in str(e) or "not found" in str(e).lower():
                raise FileNotFoundError(path) from e
            raise
        return content

    async def make_dir(self, path: str) -> None:
        await self._sandbox.files.make_dir(path)

    # -- Command Execution --

    async def run_command(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int | None = None,
    ) -> CommandResult:
        kwargs: dict[str, Any] = {}
        if cwd:
            kwargs["cwd"] = cwd
        if timeout:
            kwargs["timeout"] = timeout
        try:
            result = await self._sandbox.commands.run(command, **kwargs)
        except Exception as e:
            if _is_sandbox_dead(e):
                raise SandboxDeadError(str(e)) from e
            raise
        return CommandResult(
            exit_code=result.exit_code,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
        )

    async def send_stdin(self, pid: int, data: str) -> None:
        try:
            await self._sandbox.commands.send_stdin(pid, data)
        except Exception as e:
            if _is_sandbox_dead(e):
                raise SandboxDeadError(str(e)) from e
            raise

    async def start_session(
        self,
        command: str,
        cwd: str,
        on_stdout: Any,
    ) -> int:
        """Start a long-lived session process with stdin + stdout streaming.

        Returns the PID. The process stays alive until killed. Use
        ``send_stdin(pid, data)`` to write JSON lines to the process.
        ``on_stdout`` fires as NDJSON lines arrive from the process.
        """
        kwargs: dict[str, Any] = {
            "background": True,
            "timeout": 0,
            "stdin": True,
            "on_stdout": on_stdout,
        }
        if cwd:
            kwargs["cwd"] = cwd
        try:
            handle = await self._sandbox.commands.run(command, **kwargs)
        except Exception as e:
            if _is_sandbox_dead(e):
                raise SandboxDeadError(str(e)) from e
            raise
        pid: int = handle.pid
        logger.info("Persistent process started: pid=%d cmd=%s", pid, command[:200])
        return pid

    # -- Native Git (E2B-specific, not on base SandboxProvider protocol) --

    async def git_clone(
        self,
        url: str,
        path: str,
        *,
        branch: str | None = None,
        depth: int | None = None,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        kwargs: dict[str, Any] = {"path": path}
        if branch:
            kwargs["branch"] = branch
        if depth:
            kwargs["depth"] = depth
        if username:
            kwargs["username"] = username
        if password:
            kwargs["password"] = password
        await self._sandbox.git.clone(url, **kwargs)

    async def git_add(self, path: str, *, files: list[str] | None = None) -> None:
        kwargs: dict[str, Any] = {}
        if files:
            kwargs["files"] = files
        await self._sandbox.git.add(path, **kwargs)

    async def git_commit(self, path: str, message: str) -> None:
        await self._sandbox.git.commit(path, message)

    async def git_push(
        self,
        path: str,
        *,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        kwargs: dict[str, Any] = {}
        if username:
            kwargs["username"] = username
        if password:
            kwargs["password"] = password
        await self._sandbox.git.push(path, **kwargs)

    async def git_status(self, path: str) -> Any:
        from harnessbox.workspace import GitStatus

        status = await self._sandbox.git.status(path)
        return GitStatus(
            branch=getattr(status, "current_branch", "unknown"),
            ahead=getattr(status, "ahead", 0),
            behind=getattr(status, "behind", 0),
            dirty=len(getattr(status, "file_status", [])) > 0,
        )

    async def git_configure_user(self, name: str, email: str, *, path: str | None = None) -> None:
        kwargs: dict[str, Any] = {}
        if path:
            kwargs["scope"] = "local"
            kwargs["path"] = path
        await self._sandbox.git.configure_user(name, email, **kwargs)

    async def git_dangerously_authenticate(
        self, username: str, password: str, *, host: str = "github.com"
    ) -> None:
        await self._sandbox.git.dangerously_authenticate(
            username=username, password=password, host=host
        )

    async def git_create_branch(self, path: str, branch: str) -> None:
        await self._sandbox.git.create_branch(path, branch)

    async def git_set_config(
        self, key: str, value: str, *, scope: str = "global", path: str | None = None
    ) -> None:
        kwargs: dict[str, Any] = {"scope": scope}
        if path:
            kwargs["path"] = path
        await self._sandbox.git.set_config(key, value, **kwargs)

    # -- PTY (E2B-specific, not on base SandboxProvider protocol) --

    async def pty_create(
        self,
        on_data: Any,
        *,
        cols: int = 80,
        rows: int = 24,
        cwd: str | None = None,
        timeout: int = 0,
    ) -> int:
        kwargs: dict[str, Any] = {
            "cols": cols,
            "rows": rows,
            "on_data": on_data,
            "timeout": timeout,
        }
        if cwd:
            kwargs["cwd"] = cwd
        terminal = await self._sandbox.pty.create(**kwargs)
        return terminal.pid

    async def pty_send(self, pid: int, data: bytes) -> None:
        await self._sandbox.pty.send_stdin(pid, data)

    async def pty_kill(self, pid: int) -> None:
        await self._sandbox.pty.kill(pid)

    async def stream_command(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int | None = None,
    ) -> AsyncGenerator[str, None]:
        effective_timeout = timeout or self._timeout
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        buffer = ""
        loop = asyncio.get_running_loop()

        def on_stdout(data: Any) -> None:
            nonlocal buffer
            raw = data.line if hasattr(data, "line") else str(data)
            logger.debug("E2B stdout raw: %s", raw[:200])
            buffer += raw + "\n"
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if line:
                    logger.debug("E2B queued line: %s", line[:200])
                    loop.call_soon_threadsafe(queue.put_nowait, line)

        async def _run() -> None:
            nonlocal buffer
            try:
                result = await self._sandbox.commands.run(
                    command,
                    on_stdout=on_stdout,
                    timeout=effective_timeout,
                    cwd=cwd,
                )
                if buffer.strip():
                    loop.call_soon_threadsafe(queue.put_nowait, buffer.strip())
                if result.exit_code != 0 and result.stderr:
                    loop.call_soon_threadsafe(
                        queue.put_nowait,
                        json.dumps(
                            {
                                "type": "_process_error",
                                "exit_code": result.exit_code,
                                "stderr": result.stderr[:2000],
                            }
                        ),
                    )
            except Exception as e:
                if _is_sandbox_dead(e):
                    raise SandboxDeadError(str(e)) from e
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    json.dumps(
                        {
                            "type": "_process_error",
                            "exit_code": -1,
                            "stderr": str(e)[:2000],
                        }
                    ),
                )
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        task = asyncio.create_task(_run())

        try:
            while True:
                try:
                    line = await asyncio.wait_for(queue.get(), timeout=effective_timeout)
                except asyncio.TimeoutError:
                    yield json.dumps(
                        {
                            "type": "_process_error",
                            "exit_code": -1,
                            "stderr": f"No output for {effective_timeout}s — timed out",
                        }
                    )
                    break
                if line is None:
                    break
                yield line
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
