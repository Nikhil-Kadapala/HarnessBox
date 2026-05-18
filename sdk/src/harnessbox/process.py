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
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any

from harnessbox.cost import CostMetrics, ModelCost, parse_cost_data
from harnessbox.providers import SandboxProvider
from harnessbox.status import parse_context_output
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

    def __init__(
        self,
        provider: SandboxProvider,
        parser: StreamParser,
        *,
        turn_timeout: float = 300,
    ) -> None:
        self._provider = provider
        self._parser = parser
        self._pid: int | None = None
        self._stdout_queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._turn_timeout = turn_timeout
        self._turn_active = False
        self._cost_metrics = CostMetrics()

    @property
    def is_running(self) -> bool:
        """Return whether the agent process is currently running."""
        return self._running

    @property
    def pid(self) -> int | None:
        """Return the PID of the running agent process, or None if not started."""
        return self._pid

    @property
    def cost_metrics(self) -> CostMetrics:
        """Return accumulated cost metrics across all turns."""
        return self._cost_metrics

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

        _log.info("Starting session process: %s", command[:200])
        self._pid = await self._provider.start_session(command, cwd, on_stdout)
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
        self._turn_active = True
        try:
            while True:
                try:
                    line = await asyncio.wait_for(
                        self._stdout_queue.get(), timeout=self._turn_timeout
                    )
                except asyncio.TimeoutError:
                    _log.warning("No output for %ss — turn timed out", self._turn_timeout)
                    yield self._parser._make_event(
                        EventType.ERROR,
                        error_message=f"No output for {int(self._turn_timeout)}s — turn timed out",
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
        finally:
            self._turn_active = False

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

    async def poll_status(
        self, *, skip_cost: bool = False, session_id: str = ""
    ) -> list[UniversalEvent]:
        """Run /context and optionally /cost after a turn, return typed events.

        Must only be called between turns (after stream_turn completes).
        Raises RuntimeError if called during an active turn.
        """
        if self._turn_active:
            raise RuntimeError("Cannot poll status during an active turn")
        if not self._running or self._pid is None:
            return []

        now = datetime.now(timezone.utc).isoformat()
        events: list[UniversalEvent] = []

        try:
            context_data = await self.send_command("/context", timeout=5)
            cost_data = await self.send_command("/cost", timeout=5) if not skip_cost else {}
        except asyncio.TimeoutError:
            _log.warning("Status poll timed out")
            return []
        except Exception as e:
            _log.warning("Status poll failed: %s", e)
            return []

        context_output = context_data.get("output", "")
        if context_output:
            parsed = parse_context_output(context_output)
            if parsed:
                events.append(
                    UniversalEvent(
                        event_id=str(uuid.uuid4()),
                        sequence=0,
                        timestamp=now,
                        session_id=session_id,
                        event_type=EventType.CONTEXT_UPDATE,
                        metadata=parsed,
                    )
                )

        if not skip_cost and cost_data:
            try:
                parsed_cost = parse_cost_data(cost_data)
                if parsed_cost:
                    self._cost_metrics = CostMetrics(
                        total_cost_usd=parsed_cost.total_cost_usd,
                        per_model=parsed_cost.per_model,
                        turn_count=self._cost_metrics.turn_count + 1,
                        last_updated=parsed_cost.last_updated,
                    )
                    events.append(
                        UniversalEvent(
                            event_id=str(uuid.uuid4()),
                            sequence=0,
                            timestamp=now,
                            session_id=session_id,
                            event_type=EventType.COST_UPDATE,
                            metadata={
                                "total_cost_usd": self._cost_metrics.total_cost_usd,
                                "turn_count": self._cost_metrics.turn_count,
                                "per_model": {
                                    model: {
                                        "input_tokens": mc.input_tokens,
                                        "output_tokens": mc.output_tokens,
                                        "cost_usd": mc.cost_usd,
                                    }
                                    for model, mc in self._cost_metrics.per_model.items()
                                },
                            },
                        )
                    )
            except Exception as e:
                _log.warning("Failed to parse cost data: %s", e)

        return events

    def cost_update_from_result(
        self, turn_end_event: UniversalEvent, *, session_id: str = ""
    ) -> UniversalEvent | None:
        """Build a COST_UPDATE event from enriched result metadata.

        Updates internal cost_metrics. Returns the event or None if no
        model_usage data is present in the turn-end event.
        """
        metadata = turn_end_event.metadata or {}
        model_usage = metadata.get("model_usage", {})

        if not model_usage:
            return None

        total_cost = turn_end_event.cost_usd

        per_model: dict[str, ModelCost] = {}
        for model_name, usage in model_usage.items():
            if not isinstance(usage, dict):
                continue
            input_tokens = usage.get("inputTokens", usage.get("input_tokens", 0))
            output_tokens = usage.get("outputTokens", usage.get("output_tokens", 0))
            per_model[model_name] = ModelCost(
                input_tokens=int(input_tokens or 0),
                output_tokens=int(output_tokens or 0),
                cost_usd=0.0,
            )

        self._cost_metrics = CostMetrics(
            total_cost_usd=float(total_cost) if total_cost else self._cost_metrics.total_cost_usd,
            per_model=per_model,
            turn_count=self._cost_metrics.turn_count + 1,
            last_updated=datetime.now(timezone.utc).isoformat(),
        )

        return UniversalEvent(
            event_id=str(uuid.uuid4()),
            sequence=0,
            timestamp=datetime.now(timezone.utc).isoformat(),
            session_id=session_id,
            event_type=EventType.COST_UPDATE,
            metadata={
                "total_cost_usd": self._cost_metrics.total_cost_usd,
                "turn_count": self._cost_metrics.turn_count,
                "per_model": {
                    model: {
                        "input_tokens": mc.input_tokens,
                        "output_tokens": mc.output_tokens,
                        "cost_usd": mc.cost_usd,
                    }
                    for model, mc in self._cost_metrics.per_model.items()
                },
            },
        )

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
