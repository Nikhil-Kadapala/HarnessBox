"""Persistent agent process — stdin/stdout JSON-line protocol.

Manages a long-lived CLI subprocess inside a sandbox. Prompts are sent
via stdin as JSON lines, responses stream from stdout as NDJSON.
The process stays alive across turns.

Ported from Sandbox Agent's AdapterRuntime pattern + Claude Agent SDK's
persistent ``--input-format stream-json`` mode.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from harnessbox.providers import SandboxProvider, SessionProcessCapable
from harnessbox.streaming import EventType, StreamParser, UniversalEvent

_log = logging.getLogger("harnessbox.process")


class AgentProcess:
    """Persistent agent CLI process with bidirectional JSON-line control.

    The process is started once and stays alive across multiple prompt turns.
    Each turn: ``send_prompt()`` writes to stdin, ``stream_turn()`` yields
    events from stdout until a ``result`` message signals turn completion.

    Permission requests (``control_request``) are emitted as events. The
    caller can respond via ``respond_permission()``.
    """

    def __init__(self, provider: SandboxProvider, parser: StreamParser) -> None:
        self._provider = provider
        self._parser = parser
        self._pid: int | None = None
        self._stdout_queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._running = False

    @property
    def is_running(self) -> bool:
        """Return whether the agent process is currently running."""
        return self._running

    @property
    def pid(self) -> int | None:
        """Return the PID of the running agent process, or None if not started."""
        return self._pid

    async def start(self, command: str, cwd: str) -> None:
        """Launch the agent as a persistent background process."""
        if self._running:
            raise RuntimeError("Agent process already running")

        loop = asyncio.get_running_loop()
        buffer = ""

        def on_stdout(data: Any) -> None:
            nonlocal buffer
            raw = data.line if hasattr(data, "line") else str(data)
            _log.debug("stdout raw: %s", raw[:1000])
            buffer += raw + "\n"
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if line:
                    loop.call_soon_threadsafe(self._stdout_queue.put_nowait, line)

        if isinstance(self._provider, SessionProcessCapable):
            _log.info("Starting session process (native): %s", command[:200])
            self._pid = await self._provider.start_session(command, cwd, on_stdout)
            self._running = True
        else:
            _log.info("Starting persistent process (background task): %s", command[:200])
            handle = await self._provider.run_background(command, cwd=cwd)
            self._pid = handle.pid
            self._running = True

        _log.info("Agent process started: pid=%s", self._pid)

    async def send_prompt(self, text: str) -> None:
        """Send a user message to the agent's stdin as a JSON line.

        Retries once on transient sandbox errors (e.g., sandbox resuming
        from pause via E2B AutoResume).
        """
        if not self._running or self._pid is None:
            raise RuntimeError("Agent process not running")
        msg = json.dumps({"type": "user", "message": {"role": "user", "content": text}})
        _log.info("Sending prompt: %s", msg[:200])

        last_err: Exception | None = None
        for attempt in range(3):
            try:
                await self._provider.send_stdin(self._pid, msg + "\n")
                return
            except Exception as e:
                last_err = e
                err_str = str(e).lower()
                if "not found" in err_str or "unavailable" in err_str:
                    if attempt < 2:
                        _log.info("Sandbox may be resuming, retry %d/2...", attempt + 1)
                        await asyncio.sleep(2)
                        continue
                    self._running = False
                    raise RuntimeError(
                        "Sandbox has timed out or been destroyed. Create a new session."
                    ) from e
                raise
        if last_err:
            raise last_err

    async def stream_turn(self) -> AsyncGenerator[UniversalEvent, None]:
        """Yield events from stdout until the turn completes.

        A turn ends when a ``result`` message is received. The process
        stays alive for the next ``send_prompt()`` call.
        """
        while True:
            try:
                line = await asyncio.wait_for(self._stdout_queue.get(), timeout=300)
            except asyncio.TimeoutError:
                _log.warning("No output for 300s — turn timed out")
                yield self._parser._make_event(
                    EventType.ERROR,
                    error_message="No output for 300s — turn timed out",
                )
                return

            if line is None:
                _log.info("Agent process exited during turn")
                return

            _log.debug("Turn line: %s", line[:1000])
            for event in self._parser.parse_line(line):
                _log.info("Parsed event: %s (error: %s)", event.event_type, event.error_message)
                yield event
                if event.event_type in (EventType.SESSION_ENDED, EventType.TURN_ENDED):
                    if event.cost_usd is not None or event.duration_ms is not None:
                        return

    async def send_command(self, command: str, timeout: float = 10) -> dict[str, Any]:
        """Send a slash command and return collected response data.

        Slash commands (``/context``, ``/cost``, ``/compact``) use the
        same stdin JSON-line format as prompts. The response comes as
        multiple messages: a ``system.init``, optionally a ``user`` message
        with the command output as ``<local-command-stdout>`` content,
        and finally a ``result`` message.

        Returns a dict with ``result`` data merged with any ``user``
        message content found.
        """
        if not self._running or self._pid is None:
            raise RuntimeError("Agent process not running")
        msg = json.dumps({"type": "user", "message": {"role": "user", "content": command}})
        _log.info("Sending command: %s", command)
        await self._provider.send_stdin(self._pid, msg + "\n")

        collected: dict[str, Any] = {}
        while True:
            try:
                line = await asyncio.wait_for(self._stdout_queue.get(), timeout=timeout)
            except asyncio.TimeoutError:
                _log.warning("Command %s timed out after %ss", command, timeout)
                return collected
            if line is None:
                return collected
            try:
                data = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            msg_type = data.get("type")
            if msg_type == "user":
                content = data.get("message", {}).get("content", "")
                output = self._extract_text_content(content)
                if output:
                    collected["output"] = output
                    _log.debug("Command output captured: %s", output[:200])
            elif msg_type == "result":
                collected.update(data)
                _log.debug(
                    "Command result: %s",
                    {k: v for k, v in collected.items() if k != "raw"}.__repr__()[:300],
                )
                return collected

    @classmethod
    def _extract_text_content(cls, content: Any) -> str:
        """Extract text from Claude message content blocks."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = [cls._extract_text_content(item) for item in content]
            return "\n".join(part for part in parts if part)
        if not isinstance(content, dict):
            return ""

        text_parts: list[str] = []
        for key in ("text", "output"):
            value = content.get(key)
            if isinstance(value, str):
                text_parts.append(value)

        nested_content = content.get("content")
        if nested_content is not None:
            nested = cls._extract_text_content(nested_content)
            if nested:
                text_parts.append(nested)

        return "\n".join(text_parts)

    async def respond_permission(self, request_id: str, behavior: str = "allow") -> None:
        """Respond to a control_request permission gate."""
        if not self._running or self._pid is None:
            raise RuntimeError("Agent process not running")
        msg = json.dumps(
            {
                "type": "control_response",
                "request_id": request_id,
                "response": {"subtype": "success", "response": {"behavior": behavior}},
            }
        )
        _log.info("Permission response: %s -> %s", request_id, behavior)
        await self._provider.send_stdin(self._pid, msg + "\n")

    async def stop(self) -> None:
        """Kill the agent process and clean up."""
        _log.info("Stopping agent process")
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._pid = None
