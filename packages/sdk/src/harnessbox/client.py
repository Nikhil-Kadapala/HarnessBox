"""HarnessBox Python client — connects to a HarnessBox server via HTTP/SSE.

Install the client extra to use this module:
    pip install harnessbox[client]
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from harnessbox.lifecycle import RuntimeState
from harnessbox.streaming import EventType, UniversalEvent

try:
    import httpx
except ImportError as _err:
    raise ImportError(
        "httpx is required to use HarnessBoxClient. Install it with: pip install harnessbox[client]"
    ) from _err

_TERMINAL_STATES = frozenset(
    {RuntimeState.ERROR.value, RuntimeState.DEAD.value, RuntimeState.ENDED.value}
)


@dataclass
class WorkspaceInfo:
    """Client-side view of a workspace.

    Mirrors the server's SessionResponse fields without Pydantic — safe to
    import without the server extra installed. Field names and optionality
    track ``_server/routers/_models.py::SessionResponse``.
    """

    workspace_id: str
    harness: str
    runtime_state: str
    workflow_state: str
    created_at: str
    workspace_name: str | None = None
    branch: str | None = None
    base_branch: str | None = None
    remote: str | None = None
    pr_url: str | None = None
    pr_number: int | None = None
    ci_status: str | None = None
    total_cost_usd: float = 0.0
    error_message: str | None = None


class WorkspaceCreationError(Exception):
    """Raised when workspace creation fails."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        runtime_state: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.runtime_state = runtime_state


class PromptStreamError(Exception):
    """Raised when the server emits an error event on a prompt SSE stream."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.error_message = message


class HarnessBoxClient:
    """Async HTTP client for the HarnessBox server API.

    Handles the 202-pattern workspace creation (POST → subscribe SSE →
    wait for ACTIVE) and streaming prompt responses.

    Usage::

        async with HarnessBoxClient("http://localhost:8000") as client:
            ws = await client.create_workspace(
                remote="https://github.com/org/repo",
                branch="main",
            )
            async for event in client.prompt(ws.workspace_id, "Hello"):
                print(event.delta or "")
    """

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        headers: dict[str, str] = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout,
        )

    async def create_workspace(
        self,
        remote: str,
        branch: str,
        provider: str = "e2b",
        provider_api_key: str | None = None,
        timeout: float = 120.0,
    ) -> WorkspaceInfo:
        """Create a workspace and wait until it becomes ACTIVE.

        Issues POST /v1/workspaces (202), then subscribes to the events
        SSE stream until the workspace reaches ACTIVE or a terminal state.

        The request body matches the server's ``CreateSessionRequest``: git
        settings are nested under ``workspace`` and the provider key is sent as
        ``api_key``. The harness is fixed server-side (claude-code); pass a
        harness per-turn to ``prompt()`` instead.

        Args:
            remote: Git remote URL for the workspace repository.
            branch: Branch to check out.
            provider: Sandbox provider (default: "e2b").
            provider_api_key: API key forwarded to the sandbox provider
                (e.g. E2B_API_KEY). Distinct from the Bearer token used
                for server authentication.
            timeout: Seconds to wait for the workspace to become ACTIVE.

        Returns:
            WorkspaceInfo with runtime_state == "active".

        Raises:
            WorkspaceCreationError: HTTP error, ERROR/DEAD/ENDED state, or timeout.
        """
        payload: dict[str, Any] = {
            "provider": provider,
            "workspace": {"remote": remote, "branch": branch},
        }
        if provider_api_key is not None:
            payload["api_key"] = provider_api_key

        resp = await self._client.post("/v1/workspaces", json=payload)
        if resp.status_code not in (200, 201, 202):
            raise WorkspaceCreationError(
                f"Failed to create workspace: {resp.text}",
                status_code=resp.status_code,
            )

        data: dict[str, Any] = resp.json()
        workspace_id: str = data["session_id"]

        try:
            return await asyncio.wait_for(
                self._wait_until_active(workspace_id, data),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            raise WorkspaceCreationError(
                f"Workspace {workspace_id!r} did not become ACTIVE within {timeout}s",
                runtime_state=RuntimeState.STARTING.value,
            ) from None

    async def _wait_until_active(
        self,
        workspace_id: str,
        initial_data: dict[str, Any],
    ) -> WorkspaceInfo:
        """Subscribe to the events SSE stream until terminal or ACTIVE."""
        if initial_data.get("runtime_state") == RuntimeState.ACTIVE.value:
            return _parse_workspace_info(initial_data)

        async with self._client.stream(
            "GET",
            f"/v1/workspaces/{workspace_id}/events",
            timeout=None,
        ) as response:
            if response.status_code != 200:
                await response.aread()
                raise WorkspaceCreationError(
                    f"Failed to subscribe to events: {response.text}",
                    status_code=response.status_code,
                )
            async for line in _iter_sse_lines(response):
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Full UniversalEvent format (ACTIVE from event buffer):
                # {"type": "runtime.state", "message": {"metadata": {"runtime_state": "active"}}}
                if payload.get("type") == EventType.RUNTIME_STATE.value:
                    meta = payload.get("message", {}).get("metadata", {})
                    state: str = meta.get("runtime_state", "")
                    if state == RuntimeState.ACTIVE.value:
                        return await self.get_workspace(workspace_id)
                    if state in _TERMINAL_STATES:
                        err = meta.get("error_message") or "Unknown error"
                        raise WorkspaceCreationError(
                            f"Workspace {workspace_id!r} entered {state!r}: {err}",
                            runtime_state=state,
                        )

                # Flat provisioning format (terminal states only):
                # {"event_type": "runtime.state", "metadata": {"runtime_state": "error"}}
                if payload.get("event_type") == EventType.RUNTIME_STATE.value:
                    meta = payload.get("metadata", {})
                    state = meta.get("runtime_state", "")
                    if state in _TERMINAL_STATES:
                        err = meta.get("error_message") or "Unknown error"
                        raise WorkspaceCreationError(
                            f"Workspace {workspace_id!r} entered {state!r}: {err}",
                            runtime_state=state,
                        )

        # Stream ended without an explicit ACTIVE/terminal signal. Reconcile
        # against the server's current state rather than returning a possibly
        # still-provisioning workspace (the contract is "blocks until ACTIVE").
        info = await self.get_workspace(workspace_id)
        if info.runtime_state == RuntimeState.ACTIVE.value:
            return info
        if info.runtime_state in _TERMINAL_STATES:
            raise WorkspaceCreationError(
                f"Workspace {workspace_id!r} entered {info.runtime_state!r}: "
                f"{info.error_message or 'Unknown error'}",
                runtime_state=info.runtime_state,
            )
        raise WorkspaceCreationError(
            f"Event stream ended before workspace {workspace_id!r} became ACTIVE "
            f"(state: {info.runtime_state!r})",
            runtime_state=info.runtime_state,
        )

    async def get_workspace(self, workspace_id: str) -> WorkspaceInfo:
        """Fetch current workspace state from the server."""
        resp = await self._client.get(f"/v1/workspaces/{workspace_id}")
        resp.raise_for_status()
        return _parse_workspace_info(resp.json())

    async def prompt(
        self,
        workspace_id: str,
        text: str,
        harness: str = "claude-code",
        conversation_id: str | None = None,
    ) -> AsyncGenerator[UniversalEvent, None]:
        """Send a prompt and yield UniversalEvent objects from the SSE stream.

        The generator yields events until the server sends the [DONE] sentinel.
        Malformed JSON lines and unknown enum values are silently skipped.

        Usage::

            async for event in client.prompt(ws_id, "Hello"):
                if event.delta:
                    print(event.delta, end="", flush=True)

        Args:
            workspace_id: Target workspace identifier.
            text: Prompt text to send to the agent.
            harness: Agent harness name.
            conversation_id: Optional conversation ID for multi-turn sessions.

        Yields:
            UniversalEvent objects reconstructed from the server's SSE stream.
        """
        payload: dict[str, Any] = {"prompt": text, "harness": harness}
        if conversation_id is not None:
            payload["conversation_id"] = conversation_id

        async with self._client.stream(
            "POST",
            f"/v1/workspaces/{workspace_id}/prompt",
            json=payload,
            timeout=None,
        ) as response:
            response.raise_for_status()
            async for line in _iter_sse_lines(response):
                if line == "[DONE]":
                    return
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # Server signals a mid-stream failure with a flat error frame
                # ({"event_type": "error", "error_message": ...}). Surface it
                # instead of silently dropping it as an unparseable event.
                if isinstance(data, dict) and data.get("event_type") == EventType.ERROR.value:
                    raise PromptStreamError(data.get("error_message") or "Unknown stream error")
                try:
                    yield UniversalEvent.from_dict(data)
                except (KeyError, ValueError):
                    continue

    async def close(self) -> None:
        """Release the underlying HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> "HarnessBoxClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()


async def _iter_sse_lines(response: httpx.Response) -> AsyncGenerator[str, None]:
    """Yield data payloads from an SSE stream, skipping comments and blanks.

    Per the SSE spec a ``data:`` field may or may not be followed by a single
    space; strip at most one so payloads survive servers that omit it.
    """
    async for raw_line in response.aiter_lines():
        line = raw_line.strip()
        if not line or line.startswith(":"):
            continue
        if line.startswith("data:"):
            payload = line[5:]
            if payload.startswith(" "):
                payload = payload[1:]
            yield payload


def _parse_workspace_info(data: dict[str, Any]) -> WorkspaceInfo:
    """Parse a server SessionResponse JSON dict into a WorkspaceInfo.

    Only ``session_id`` and ``runtime_state`` are required; every other field
    is optional on SessionResponse and read with a default.
    """
    return WorkspaceInfo(
        workspace_id=data["session_id"],
        harness=data.get("harness", "claude-code"),
        runtime_state=data["runtime_state"],
        workflow_state=data.get("workflow_state", "in_progress"),
        created_at=data.get("created_at", ""),
        workspace_name=data.get("workspace_name"),
        branch=data.get("branch"),
        base_branch=data.get("base_branch"),
        remote=data.get("remote"),
        pr_url=data.get("pr_url"),
        pr_number=data.get("pr_number"),
        ci_status=data.get("ci_status"),
        total_cost_usd=data.get("total_cost_usd", 0.0),
        error_message=data.get("error_message"),
    )
