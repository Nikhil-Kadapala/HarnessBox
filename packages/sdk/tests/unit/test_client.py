"""Unit tests for HarnessBoxClient using respx to mock httpx."""

from __future__ import annotations

import json

import pytest
import respx
from httpx import Response

from harnessbox.client import HarnessBoxClient, WorkspaceCreationError, WorkspaceInfo
from harnessbox.lifecycle import RuntimeState
from harnessbox.streaming import EventType, UniversalEvent

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_BASE = "http://localhost:8000"

_SESSION_STARTING = {
    "session_id": "ws-1",
    "remote": "https://github.com/org/repo",
    "branch": "main",
    "provider": "e2b",
    "harness": "claude-code",
    "runtime_state": "starting",
    "workflow_state": "in_progress",
    "created_at": "2026-01-01T00:00:00Z",
    "last_active": "2026-01-01T00:00:00Z",
    "provider_sandbox_id": None,
    "sandbox_conn": None,
    "error_message": None,
}

_SESSION_ACTIVE = {**_SESSION_STARTING, "runtime_state": "active", "sandbox_conn": "sb-abc"}

_ACTIVE_STATE_EVENT = json.dumps(
    {
        "type": EventType.RUNTIME_STATE.value,
        "timestamp": "2026-01-01T00:00:00Z",
        "message": {
            "event_id": "ev-1",
            "sequence": 1,
            "session_id": "ws-1",
            "metadata": {"runtime_state": "active"},
        },
    }
)

_ERROR_STATE_FLAT = json.dumps(
    {
        "event_type": EventType.RUNTIME_STATE.value,
        "metadata": {"runtime_state": "error", "error_message": "E2B quota exceeded"},
    }
)


def _sse(data: str) -> str:
    return f"data: {data}\n\n"


def _make_prompt_event(seq: int, delta: str, session_id: str = "ws-1") -> dict[str, object]:
    return {
        "type": EventType.ITEM_DELTA.value,
        "timestamp": "2026-01-01T00:00:00Z",
        "message": {
            "event_id": f"ev-{seq}",
            "sequence": seq,
            "session_id": session_id,
            "delta": delta,
        },
    }


# ---------------------------------------------------------------------------
# WorkspaceInfo
# ---------------------------------------------------------------------------


class TestWorkspaceInfo:
    def test_fields(self) -> None:
        ws = WorkspaceInfo(
            workspace_id="ws-1",
            remote="https://github.com/org/repo",
            branch="main",
            provider="e2b",
            harness="claude-code",
            runtime_state="active",
            workflow_state="in_progress",
            created_at="2026-01-01T00:00:00Z",
            last_active="2026-01-01T00:00:00Z",
        )
        assert ws.workspace_id == "ws-1"
        assert ws.runtime_state == "active"
        assert ws.error_message is None


# ---------------------------------------------------------------------------
# UniversalEvent.from_dict
# ---------------------------------------------------------------------------


class TestUniversalEventFromDict:
    def test_roundtrip(self) -> None:
        original = UniversalEvent(
            event_id="ev-1",
            sequence=1,
            timestamp="2026-01-01T00:00:00Z",
            session_id="ws-1",
            event_type=EventType.ITEM_DELTA,
            delta="Hello",
            metadata={"foo": "bar"},
        )
        reconstructed = UniversalEvent.from_dict(original.to_dict())

        assert reconstructed.event_id == original.event_id
        assert reconstructed.sequence == original.sequence
        assert reconstructed.session_id == original.session_id
        assert reconstructed.event_type == original.event_type
        assert reconstructed.delta == original.delta
        assert reconstructed.metadata == original.metadata
        assert reconstructed.raw == original.to_dict()

    def test_runtime_state_event(self) -> None:
        data = json.loads(_ACTIVE_STATE_EVENT)
        event = UniversalEvent.from_dict(data)
        assert event.event_type == EventType.RUNTIME_STATE
        assert event.metadata["runtime_state"] == "active"

    def test_unknown_type_raises(self) -> None:
        data = {"type": "not.a.real.type", "timestamp": "", "message": {}}
        with pytest.raises(ValueError):
            UniversalEvent.from_dict(data)

    def test_missing_type_raises(self) -> None:
        data = {"timestamp": "", "message": {}}
        with pytest.raises(KeyError):
            UniversalEvent.from_dict(data)

    def test_optional_fields_default_to_none(self) -> None:
        data = {
            "type": EventType.STATUS.value,
            "timestamp": "2026-01-01T00:00:00Z",
            "message": {
                "event_id": "ev-1",
                "sequence": 0,
                "session_id": "ws-1",
            },
        }
        event = UniversalEvent.from_dict(data)
        assert event.delta is None
        assert event.item_kind is None
        assert event.cost_usd is None


# ---------------------------------------------------------------------------
# HarnessBoxClient — create_workspace
# ---------------------------------------------------------------------------


class TestCreateWorkspace:
    @pytest.mark.asyncio
    @respx.mock
    async def test_already_active_returns_immediately(self) -> None:
        respx.post(f"{_BASE}/v1/workspaces").mock(return_value=Response(200, json=_SESSION_ACTIVE))

        async with HarnessBoxClient(_BASE) as client:
            ws = await client.create_workspace(
                remote="https://github.com/org/repo",
                branch="main",
            )

        assert ws.workspace_id == "ws-1"
        assert ws.runtime_state == RuntimeState.ACTIVE.value

    @pytest.mark.asyncio
    @respx.mock
    async def test_waits_for_active_via_sse(self) -> None:
        sse_body = _sse(_ACTIVE_STATE_EVENT)
        respx.post(f"{_BASE}/v1/workspaces").mock(
            return_value=Response(202, json=_SESSION_STARTING)
        )
        respx.get(f"{_BASE}/v1/workspaces/ws-1/events").mock(
            return_value=Response(200, text=sse_body, headers={"content-type": "text/event-stream"})
        )
        respx.get(f"{_BASE}/v1/workspaces/ws-1").mock(
            return_value=Response(200, json=_SESSION_ACTIVE)
        )

        async with HarnessBoxClient(_BASE) as client:
            ws = await client.create_workspace(
                remote="https://github.com/org/repo",
                branch="main",
            )

        assert ws.runtime_state == RuntimeState.ACTIVE.value

    @pytest.mark.asyncio
    @respx.mock
    async def test_error_state_raises(self) -> None:
        sse_body = _sse(_ERROR_STATE_FLAT)
        respx.post(f"{_BASE}/v1/workspaces").mock(
            return_value=Response(202, json=_SESSION_STARTING)
        )
        respx.get(f"{_BASE}/v1/workspaces/ws-1/events").mock(
            return_value=Response(200, text=sse_body, headers={"content-type": "text/event-stream"})
        )

        async with HarnessBoxClient(_BASE) as client:
            with pytest.raises(WorkspaceCreationError) as exc_info:
                await client.create_workspace(
                    remote="https://github.com/org/repo",
                    branch="main",
                )

        err = exc_info.value
        assert err.runtime_state == RuntimeState.ERROR.value
        assert "E2B quota exceeded" in str(err)

    @pytest.mark.asyncio
    @respx.mock
    async def test_http_error_raises(self) -> None:
        respx.post(f"{_BASE}/v1/workspaces").mock(
            return_value=Response(503, text="Service unavailable")
        )

        async with HarnessBoxClient(_BASE) as client:
            with pytest.raises(WorkspaceCreationError) as exc_info:
                await client.create_workspace(
                    remote="https://github.com/org/repo",
                    branch="main",
                )

        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    @respx.mock
    async def test_provider_api_key_forwarded(self) -> None:
        captured: list[dict[str, object]] = []

        def capture(request, route):  # type: ignore[no-untyped-def]
            captured.append(json.loads(request.content))
            return Response(200, json=_SESSION_ACTIVE)

        respx.post(f"{_BASE}/v1/workspaces").mock(side_effect=capture)

        async with HarnessBoxClient(_BASE) as client:
            await client.create_workspace(
                remote="https://github.com/org/repo",
                branch="main",
                provider_api_key="e2b-secret",
            )

        assert captured[0]["provider_api_key"] == "e2b-secret"
        assert "api_key" not in captured[0]


# ---------------------------------------------------------------------------
# HarnessBoxClient — prompt
# ---------------------------------------------------------------------------


class TestPrompt:
    @pytest.mark.asyncio
    @respx.mock
    async def test_yields_universal_events(self) -> None:
        events = [
            _make_prompt_event(1, "Hello"),
            _make_prompt_event(2, " world"),
        ]
        body = "".join(_sse(json.dumps(e)) for e in events) + _sse("[DONE]")
        respx.post(f"{_BASE}/v1/workspaces/ws-1/prompt").mock(
            return_value=Response(200, text=body, headers={"content-type": "text/event-stream"})
        )

        received: list[UniversalEvent] = []
        async with HarnessBoxClient(_BASE) as client:
            async for event in client.prompt("ws-1", "Hello"):
                received.append(event)

        assert len(received) == 2
        assert received[0].delta == "Hello"
        assert received[1].delta == " world"
        assert all(e.event_type == EventType.ITEM_DELTA for e in received)

    @pytest.mark.asyncio
    @respx.mock
    async def test_stops_at_done_sentinel(self) -> None:
        body = _sse("[DONE]")
        respx.post(f"{_BASE}/v1/workspaces/ws-1/prompt").mock(
            return_value=Response(200, text=body, headers={"content-type": "text/event-stream"})
        )

        received: list[UniversalEvent] = []
        async with HarnessBoxClient(_BASE) as client:
            async for event in client.prompt("ws-1", "ping"):
                received.append(event)

        assert received == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_skips_malformed_json(self) -> None:
        body = _sse("not-json") + _sse(json.dumps(_make_prompt_event(1, "ok"))) + _sse("[DONE]")
        respx.post(f"{_BASE}/v1/workspaces/ws-1/prompt").mock(
            return_value=Response(200, text=body, headers={"content-type": "text/event-stream"})
        )

        received: list[UniversalEvent] = []
        async with HarnessBoxClient(_BASE) as client:
            async for event in client.prompt("ws-1", "test"):
                received.append(event)

        assert len(received) == 1
        assert received[0].delta == "ok"

    @pytest.mark.asyncio
    @respx.mock
    async def test_conversation_id_forwarded(self) -> None:
        captured: list[dict[str, object]] = []

        def capture(request, route):  # type: ignore[no-untyped-def]
            captured.append(json.loads(request.content))
            return Response(200, text=_sse("[DONE]"), headers={"content-type": "text/event-stream"})

        respx.post(f"{_BASE}/v1/workspaces/ws-1/prompt").mock(side_effect=capture)

        async with HarnessBoxClient(_BASE) as client:
            async for _ in client.prompt("ws-1", "hi", conversation_id="conv-42"):
                pass

        assert captured[0]["conversation_id"] == "conv-42"

    @pytest.mark.asyncio
    @respx.mock
    async def test_skips_ping_comments(self) -> None:
        body = ": ping\n\n" + _sse(json.dumps(_make_prompt_event(1, "x"))) + _sse("[DONE]")
        respx.post(f"{_BASE}/v1/workspaces/ws-1/prompt").mock(
            return_value=Response(200, text=body, headers={"content-type": "text/event-stream"})
        )

        received: list[UniversalEvent] = []
        async with HarnessBoxClient(_BASE) as client:
            async for event in client.prompt("ws-1", "ping test"):
                received.append(event)

        assert len(received) == 1


# ---------------------------------------------------------------------------
# HarnessBoxClient — get_workspace
# ---------------------------------------------------------------------------


class TestGetWorkspace:
    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_workspace_info(self) -> None:
        respx.get(f"{_BASE}/v1/workspaces/ws-1").mock(
            return_value=Response(200, json=_SESSION_ACTIVE)
        )

        async with HarnessBoxClient(_BASE) as client:
            ws = await client.get_workspace("ws-1")

        assert isinstance(ws, WorkspaceInfo)
        assert ws.workspace_id == "ws-1"
        assert ws.runtime_state == "active"

    @pytest.mark.asyncio
    @respx.mock
    async def test_raises_on_404(self) -> None:
        import httpx

        respx.get(f"{_BASE}/v1/workspaces/ws-missing").mock(
            return_value=Response(404, json={"detail": "not found"})
        )

        async with HarnessBoxClient(_BASE) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await client.get_workspace("ws-missing")


# ---------------------------------------------------------------------------
# HarnessBoxClient — api_key header
# ---------------------------------------------------------------------------


class TestApiKeyHeader:
    @pytest.mark.asyncio
    @respx.mock
    async def test_bearer_token_sent(self) -> None:
        captured_auth: list[str] = []

        def capture(request, route):  # type: ignore[no-untyped-def]
            captured_auth.append(request.headers.get("authorization", ""))
            return Response(200, json=_SESSION_ACTIVE)

        respx.post(f"{_BASE}/v1/workspaces").mock(side_effect=capture)

        async with HarnessBoxClient(_BASE, api_key="my-token") as client:
            await client.create_workspace(
                remote="https://github.com/org/repo",
                branch="main",
            )

        assert captured_auth[0] == "Bearer my-token"
