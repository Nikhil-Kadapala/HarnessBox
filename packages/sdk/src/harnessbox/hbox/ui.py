"""Rich console helpers for ``hbox`` create progress and turn streaming."""

from __future__ import annotations

from collections.abc import Callable
from typing import TextIO

from harnessbox.streaming import EventType, UniversalEvent

PrintFn = Callable[[str], None]

_MODEL_WARNING = (
    "note: model is local-only until a configure API exists — not applied to the running agent"
)


def model_not_applied_warning() -> str:
    """D2 warning shown on ``/model`` select and ``/status``."""
    return _MODEL_WARNING


class CreateProgress:
    """Map create-wait ``on_state`` callbacks to rich (or plain) progress lines.

    Does **not** open its own SSE loop — the client ``on_state`` / ``on_event``
    hooks drive this (D5).
    """

    def __init__(
        self,
        *,
        harness: str,
        print_fn: PrintFn | None = None,
        out: TextIO | None = None,
    ) -> None:
        self._harness = harness
        self._seen: set[str] = set()
        if print_fn is not None:
            self._print = print_fn
        else:
            stream = out

            def _print(msg: str) -> None:
                target = stream
                if target is None:
                    import sys

                    target = sys.stdout
                try:
                    from rich.console import Console

                    Console(file=target).print(msg)
                except ImportError:
                    print(msg, file=target)

            self._print = _print

    def registered(self, workspace_id: str) -> None:
        """Print the 202-accepted workspace id line."""
        self._print(f"    · registered  {workspace_id}")

    def on_state(self, state: str) -> None:
        """Handle a runtime state string from create-wait."""
        key = state.lower()
        if key in self._seen and key != "error":
            return
        self._seen.add(key)
        if key == "starting":
            self._print("    · provisioning")
        elif key == "active":
            self._print(f"    · active  {self._harness}")
        elif key == "error":
            self._print("    · error")
        elif key == "paused":
            self._print("    · paused")
        else:
            self._print(f"    · {key}")

    def resuming(self) -> None:
        """D3 auto-resume status line before a bare-text turn."""
        self._print("    · resuming…")


def format_turn_event(event: UniversalEvent) -> str | None:
    """Return a printable fragment for a prompt SSE event, or None to skip."""
    if event.delta:
        return event.delta
    if event.error_message:
        return f"\n[error] {event.error_message}\n"
    if event.event_type == EventType.ERROR:
        return f"\n[error] {event.error_message or 'unknown'}\n"
    # Full text parts (e.g. synthetic auth messages) when no delta streamed.
    texts = [p.text for p in event.content if p.type == "text" and p.text]
    if texts:
        return "".join(texts)
    if event.event_type.value == "tool_call" or (
        event.content and any(p.type == "tool_call" for p in event.content)
    ):
        name = None
        for part in event.content:
            if part.tool_name:
                name = part.tool_name
                break
        label = name or (event.tool_kind.value if event.tool_kind else "tool")
        return f"\n  · tool  {label}\n"
    return None
