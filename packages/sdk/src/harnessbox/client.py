"""HarnessBox Python client — connects to a HarnessBox server via HTTP/SSE.

Install the client extra to use this module:
    pip install harnessbox[client]

API-only / cloud users need only this extra — never the e2b provider SDK.
The server host (cloud or self-host) installs harnessbox[server,e2b] and holds
the provider key. In-process embedders use harnessbox[e2b] instead of this client.
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

    Mirrors ``CreateWorkspaceResponseParams`` without Pydantic — safe to import
    without the server extra installed.
    """

    workspace_id: str
    harness: str
    state: str
    created_at: str
    workspace_name: str | None = None
    branch: str | None = None
    base_branch: str | None = None
    remote: str | None = None
    file_system_path: str | None = None
    project_id: str | None = None
    total_cost_usd: float = 0.0
    error_message: str | None = None

    @property
    def runtime_state(self) -> str:
        """Alias for ``state`` (legacy name)."""
        return self.state

    @property
    def mount_path(self) -> str | None:
        """Deprecated alias for ``file_system_path``."""
        return self.file_system_path


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
        remote: str | None = None,
        branch: str = "main",
        provider: str = "e2b",
        provider_api_key: str | None = None,
        timeout: float = 120.0,
        *,
        git_token: str | None = None,
        mount_source: str | None = None,
        mount_path: str = "/workspace",
        env_vars: dict[str, str] | None = None,
    ) -> WorkspaceInfo:
        """Create a workspace and wait until it becomes ACTIVE.

        Issues POST /v1/workspaces/create (202), then subscribes to the events
        SSE stream until the workspace reaches ACTIVE or a terminal state.
        """
        payload: dict[str, Any] = {"provider": provider}
        if provider_api_key is not None:
            payload["api_key"] = provider_api_key
        if env_vars:
            payload["env_vars"] = env_vars
        if remote is not None:
            git: dict[str, Any] = {"repo_url": remote, "branch": branch}
            if git_token is not None:
                git["credentials"] = {"type": "token", "token": git_token}
            payload["git"] = git
        if mount_source is not None:
            payload["file_system"] = {"source": mount_source, "mount_path": mount_path}

        resp = await self._client.post("/v1/workspaces/create", json=payload)
        if resp.status_code not in (200, 201, 202):
            raise WorkspaceCreationError(
                f"Failed to create workspace: {resp.text}",
                status_code=resp.status_code,
            )

        data: dict[str, Any] = resp.json()
        workspace_id: str = data.get("workspace_id") or data["session_id"]

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

    async def upload_file(
        self,
        workspace_id: str,
        path: str,
        content: str | None = None,
        *,
        content_b64: str | None = None,
    ) -> None:
        """Upload a file into an existing workspace sandbox."""
        body: dict[str, Any] = {"path": path}
        if content is not None:
            body["content"] = content
        elif content_b64 is not None:
            body["content_b64"] = content_b64
        else:
            raise ValueError("Provide content or content_b64")
        resp = await self._client.post(f"/v1/workspaces/{workspace_id}/files", json=body)
        resp.raise_for_status()

    async def _wait_until_active(
        self,
        workspace_id: str,
        initial_data: dict[str, Any],
    ) -> WorkspaceInfo:
        """Subscribe to the events SSE stream until terminal or ACTIVE."""
        initial_state = initial_data.get("state") or initial_data.get("runtime_state")
        if initial_state == RuntimeState.ACTIVE.value:
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

                if payload.get("event_type") == EventType.RUNTIME_STATE.value:
                    meta = payload.get("metadata", {})
                    state = meta.get("runtime_state", "")
                    if state in _TERMINAL_STATES:
                        err = meta.get("error_message") or "Unknown error"
                        raise WorkspaceCreationError(
                            f"Workspace {workspace_id!r} entered {state!r}: {err}",
                            runtime_state=state,
                        )

        info = await self.get_workspace(workspace_id)
        if info.state == RuntimeState.ACTIVE.value:
            return info
        if info.state in _TERMINAL_STATES:
            raise WorkspaceCreationError(
                f"Workspace {workspace_id!r} entered {info.state!r}: "
                f"{info.error_message or 'Unknown error'}",
                runtime_state=info.state,
            )
        raise WorkspaceCreationError(
            f"Event stream ended before workspace {workspace_id!r} became ACTIVE "
            f"(state: {info.state!r})",
            runtime_state=info.state,
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
        """Send a prompt and yield UniversalEvent objects from the SSE stream."""
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
                if isinstance(data, dict) and data.get("event_type") == EventType.ERROR.value:
                    raise PromptStreamError(data.get("error_message") or "Unknown stream error")
                try:
                    yield UniversalEvent.from_dict(data)
                except (KeyError, ValueError):
                    continue

    async def close(self) -> None:
        """Release the underlying HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> HarnessBoxClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()


async def _iter_sse_lines(response: httpx.Response) -> AsyncGenerator[str, None]:
    """Yield data payloads from an SSE stream, skipping comments and blanks."""
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
    """Parse a server workspace JSON dict into a WorkspaceInfo."""
    workspace_id = data.get("workspace_id") or data.get("session_id")
    if not workspace_id:
        raise KeyError("workspace_id")
    state = data.get("state") or data.get("runtime_state")
    if not state:
        raise KeyError("state")
    return WorkspaceInfo(
        workspace_id=workspace_id,
        harness=data.get("harness", "claude-code"),
        state=state,
        created_at=data.get("created_at", ""),
        workspace_name=data.get("workspace_name"),
        branch=data.get("branch"),
        base_branch=data.get("base_branch"),
        remote=data.get("remote"),
        file_system_path=data.get("file_system_path") or data.get("mount_path"),
        project_id=data.get("project_id"),
        total_cost_usd=data.get("total_cost_usd", 0.0),
        error_message=data.get("error_message"),
    )
