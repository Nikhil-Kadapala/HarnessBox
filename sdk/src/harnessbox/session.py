"""Session management — create, track, and destroy sandbox sessions.

Ported from Rivet Sandbox Agent's AcpProxyRuntime pattern. Each session
wraps a Sandbox instance with an ID, status tracking, and per-session
locking for safe concurrent access.

``SessionConfig`` is a reusable configuration object — the precursor to
saved templates. ``SessionManager`` is the registry that maps session IDs
to live Sandbox instances.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harnessbox.sandbox import Sandbox
from harnessbox.security.policy import SecurityPolicy
from harnessbox.streaming import UniversalEvent
from harnessbox.workspace import Workspace


@dataclass
class SessionConfig:
    """Reusable session configuration. Pass to ``SessionManager.create_session()``.

    All fields mirror ``Sandbox.__init__`` params. This exists so configs
    can be stored, serialized, and reused across sessions (the precursor
    to saved templates).
    """

    provider: str = "e2b"
    api_key: str | None = None
    harness: str = "claude-code"
    system_prompt: str | Path | None = None
    skills: list[str | Path] = field(default_factory=list)
    skill_installs: list[str] = field(default_factory=list)
    plugins: list[str | Path] = field(default_factory=list)
    security_policy: SecurityPolicy | None = None
    workspace: Workspace | None = None
    env_vars: dict[str, str] = field(default_factory=dict)
    files: dict[str, str | Path] | list[str | Path] | None = None
    dirs: list[str] = field(default_factory=list)
    setup_script: str | None = None
    cwd: str | None = None
    timeout: int = 300
    skip_permissions: bool = False
    template: str | None = None
    session_timeout: int = 900


@dataclass
class SessionInfo:
    """Live session record."""

    session_id: str
    sandbox: Sandbox
    harness: str
    created_at: str
    status: str = "active"
    workspace_name: str | None = None


class SessionNotFoundError(KeyError):
    pass


class SessionManager:
    """Manages multiple sandbox sessions with per-session isolation.

    Thread-safe for use from a single asyncio event loop. Each session
    gets its own Sandbox instance and asyncio lock for serialized access.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, SessionInfo] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def create_session(
        self,
        config: SessionConfig,
        *,
        session_id: str | None = None,
        event_handler: Any = None,
    ) -> SessionInfo:
        sid = session_id or str(uuid.uuid4())
        lock = asyncio.Lock()
        sandbox = Sandbox(
            client=config.provider,
            api_key=config.api_key,
            harness=config.harness,
            system_prompt=config.system_prompt,
            skills=config.skills or None,
            skill_installs=config.skill_installs or None,
            plugins=config.plugins or None,
            security_policy=config.security_policy,
            workspace=config.workspace,
            env_vars=config.env_vars or None,
            files=config.files,
            dirs=config.dirs or None,
            setup_script=config.setup_script,
            cwd=config.cwd,
            timeout=config.timeout,
            skip_permissions=config.skip_permissions,
            template=config.template,
            event_handler=event_handler,
            session_timeout=config.session_timeout,
            session_lock=lock,
        )
        await sandbox.setup()

        workspace_name = None
        if config.workspace and hasattr(config.workspace, "worktree_name"):
            workspace_name = config.workspace.worktree_name

        info = SessionInfo(
            session_id=sid,
            sandbox=sandbox,
            harness=config.harness,
            created_at=datetime.now(timezone.utc).isoformat(),
            workspace_name=workspace_name,
        )
        self._sessions[sid] = info
        self._locks[sid] = lock
        return info

    def get_session(self, session_id: str) -> SessionInfo:
        if session_id not in self._sessions:
            raise SessionNotFoundError(f"Session not found: {session_id}")
        return self._sessions[session_id]

    def list_sessions(self) -> list[SessionInfo]:
        return list(self._sessions.values())

    async def prompt(self, session_id: str, prompt: str) -> AsyncGenerator[UniversalEvent, None]:
        """Stream prompt response. Marks session as ended if sandbox dies."""
        info = self.get_session(session_id)
        async with self._locks[session_id]:
            async for event in info.sandbox.run_prompt_events(prompt):
                # Check for sandbox death
                if (
                    event.event_type == "error"
                    and event.metadata.get("error_code") == "SANDBOX_DEAD"
                ):
                    # Mark session as ended (sandbox is dead)
                    info.status = "ended"

                yield event

    async def destroy_session(self, session_id: str) -> None:
        info = self.get_session(session_id)
        async with self._locks[session_id]:
            await info.sandbox.kill()
            info.status = "ended"
        self._sessions.pop(session_id, None)
        self._locks.pop(session_id, None)

    async def shutdown_all(self) -> None:
        for sid in list(self._sessions):
            try:
                await self.destroy_session(sid)
            except Exception:
                pass
