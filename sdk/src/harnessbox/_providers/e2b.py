"""E2B sandbox provider — wraps e2b.AsyncSandbox."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from harnessbox.providers import CommandHandle, CommandResult

logger = logging.getLogger("harnessbox.e2b")


class E2BProvider:
    """SandboxProvider implementation backed by E2B's AsyncSandbox.

    Requires the ``e2b`` package to be installed separately.
    """

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
    ) -> None:
        async_sandbox_cls = self._get_sdk()
        self._sandbox = await async_sandbox_cls.create(
            template=self._template,
            api_key=self._api_key,
            envs=env_vars or {},
            timeout=timeout,
            lifecycle={
                "on_timeout": "pause",
                "auto_resume": True,
            },
        )

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

    # -- File I/O --

    async def write_file(self, path: str, content: str) -> None:
        await self._sandbox.files.write(path, content)

    async def read_file(self, path: str) -> str:
        content: str = await self._sandbox.files.read(path)
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
        result = await self._sandbox.commands.run(command, **kwargs)
        return CommandResult(
            exit_code=result.exit_code,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
        )

    async def run_background(
        self,
        command: str,
        cwd: str | None = None,
    ) -> CommandHandle:
        kwargs: dict[str, Any] = {"background": True, "timeout": 0}
        if cwd:
            kwargs["cwd"] = cwd
        handle = await self._sandbox.commands.run(command, **kwargs)
        return CommandHandle(pid=handle.pid)

    async def send_stdin(self, pid: int, data: str) -> None:
        await self._sandbox.commands.send_stdin(pid, data)

    # -- Persistent process (E2B-specific) --

    async def start_persistent(
        self,
        command: str,
        cwd: str,
        on_stdout: Any,
    ) -> int:
        """Start a long-lived background process with stdin + stdout streaming.

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
        handle = await self._sandbox.commands.run(command, **kwargs)
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
