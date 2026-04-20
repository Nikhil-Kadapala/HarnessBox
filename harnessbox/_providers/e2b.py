"""E2B sandbox provider — wraps e2b.AsyncSandbox."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any

from harnessbox.providers import CommandHandle, CommandResult


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
            buffer += data.line if hasattr(data, "line") else str(data)
            buffer += "\n"
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if line:
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
