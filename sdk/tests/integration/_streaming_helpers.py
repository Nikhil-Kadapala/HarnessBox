"""Shared helpers for streaming parser tests."""

from __future__ import annotations

import json


def _line(**kwargs: object) -> str:
    return json.dumps(kwargs)


def _stream_event(event_type: str, **extra: object) -> str:
    return json.dumps({"type": "stream_event", "event": {"type": event_type, **extra}})
