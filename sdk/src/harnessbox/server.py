"""HTTP/SSE transport layer for HarnessBox sessions.

Exposes session management and agent event streaming over HTTP.
Install with ``pip install harnessbox[server]`` for dependencies.

    uvicorn harnessbox.server:create_app --factory --port 8000

Endpoints:
    GET    /v1/workspace/name        — generate workspace name
    GET    /v1/workspace/detect      — detect repo from path
    POST   /v1/sessions              — create session
    GET    /v1/sessions              — list sessions
    GET    /v1/sessions/{id}         — get session info
    DELETE /v1/sessions/{id}         — destroy session
    POST   /v1/sessions/{id}/prompt  — send prompt, SSE response
    GET    /v1/sessions/{id}/events  — subscribe to events (SSE)
    POST   /v1/sessions/{id}/permission — respond to permission request
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import Response
    from pydantic import BaseModel, field_validator
    from sse_starlette.sse import EventSourceResponse
except ImportError as e:
    raise ImportError(
        "Server dependencies not installed. Run: pip install harnessbox[server]"
    ) from e

from harnessbox.session import SessionConfig, SessionManager, SessionNotFoundError

logging.basicConfig(level=logging.DEBUG, format="%(name)s %(levelname)s: %(message)s")
logger = logging.getLogger("harnessbox.server")

_PROVIDER_KEY_NAMES: dict[str, list[str]] = {
    "e2b": ["E2B_API_KEY", "E2B_ACCESS_TOKEN"],
}

_OTHER_AGENT_KEYS: tuple[str, ...] = (
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
)


def _inject_host_env_vars(env_vars: dict[str, str]) -> None:
    """Auto-inject host credentials the agent needs inside the sandbox.

    Reads Claude Code auth mode from ~/.claude/settings.json and builds
    the appropriate credential set (Bedrock, Vertex, or direct API key).
    Also injects other agent API keys (OpenAI, Gemini) from host env.

    User-provided env vars always take priority (not overwritten).
    """
    import os

    from harnessbox.credentials import build_claude_env_vars

    claude_envs = build_claude_env_vars()
    for k, v in claude_envs.items():
        env_vars.setdefault(k, v)

    for key in _OTHER_AGENT_KEYS:
        if key not in env_vars:
            val = os.environ.get(key, "").strip()
            if val:
                env_vars[key] = val


def _extract_provider_key(provider: str, env_vars: dict[str, str]) -> str | None:
    """Resolve provider API key from: request env_vars → host env → CLI config files."""
    import json
    import os
    from pathlib import Path

    for key_name in _PROVIDER_KEY_NAMES.get(provider, []):
        if key_name in env_vars:
            return env_vars[key_name]

    for key_name in _PROVIDER_KEY_NAMES.get(provider, []):
        val = os.environ.get(key_name, "").strip()
        if val:
            return val

    if provider == "e2b":
        try:
            config_path = Path.home() / ".e2b" / "config.json"
            if config_path.is_file():
                data = json.loads(config_path.read_text(encoding="utf-8"))
                for field in ("teamApiKey", "accessToken"):
                    val = (data.get(field) or "").strip()
                    if val:
                        return val
        except Exception:
            pass

    return None


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class SecurityPolicyRequest(BaseModel):
    denied_tools: list[str] = []
    denied_bash_patterns: list[str] = []
    deny_network: bool = False
    credential_guards: bool | list[str] = True

    @field_validator("credential_guards", mode="before")
    @classmethod
    def _coerce_guards(cls, v: object) -> bool | list[str]:
        if isinstance(v, (bool, list)):
            return v
        if isinstance(v, str):
            return [v]
        return True


class WorkspaceRequest(BaseModel):
    remote: str
    branch: str = "main"
    auth_token: str | None = None
    clone_depth: int = 1  # Shallow clone by default for faster setup
    clone_dir_name: str | None = None  # Subdirectory name for clone (e.g., city name)
    commit_on_exit: bool = False


class CreateSessionRequest(BaseModel):
    provider: str = "e2b"
    api_key: str | None = None
    harness: str = "claude-code"
    env_vars: dict[str, str] = {}
    setup_script: str | None = None
    cwd: str | None = None
    sandbox_timeout: int = 1800
    session_timeout: int = 900
    skip_permissions: bool = False
    template: str | None = None
    session_id: str | None = None
    security_policy: SecurityPolicyRequest | None = None
    workspace: WorkspaceRequest | None = None


class SessionResponse(BaseModel):
    session_id: str
    harness: str
    status: str
    created_at: str
    workspace_name: str | None = None


class PromptRequest(BaseModel):
    prompt: str


class PermissionRequest(BaseModel):
    request_id: str
    behavior: str = "allow"


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(*, manager: SessionManager | None = None) -> FastAPI:
    """Create a FastAPI app wired to the given SessionManager."""
    mgr = manager or SessionManager()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        yield
        await mgr.shutdown_all()

    app = FastAPI(
        title="HarnessBox",
        version="0.2.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ----- Discovery endpoints (read-only) -----

    @app.get("/v1/credentials/status")
    async def get_credentials() -> dict[str, Any]:
        from harnessbox.credentials import detect_credentials

        status = detect_credentials()
        return {
            "probes": [{"name": p.name, "available": p.available} for p in status.probes],
            "timestamp": status.timestamp,
        }

    @app.get("/v1/harnesses")
    async def list_harnesses() -> list[dict[str, Any]]:
        from harnessbox.config.harness import get_harness_type, list_harness_types

        result = []
        for name in list_harness_types():
            cfg = get_harness_type(name)
            result.append(
                {
                    "name": cfg.name,
                    "cli_command": cfg.cli_command,
                    "supports_persistent": cfg.supports_persistent,
                    "default_template": cfg.default_template,
                    "workspace_root": cfg.workspace_root,
                }
            )
        return result

    @app.get("/v1/providers")
    async def list_available_providers() -> list[dict[str, str]]:
        from harnessbox._providers import list_providers

        return [{"name": p} for p in list_providers()]

    @app.get("/v1/guards")
    async def list_guards() -> list[dict[str, Any]]:
        from harnessbox.security.guards import GUARD_CATALOG

        return [
            {
                "name": gs.name,
                "bash_deny_count": len(gs.bash_deny_globs),
                "read_deny_count": len(gs.read_deny_globs),
            }
            for gs in GUARD_CATALOG.values()
        ]

    # ----- Workspace endpoints -----

    @app.get("/v1/workspace/name")
    async def generate_workspace_name() -> dict[str, str]:
        """Generate a unique city name for a new workspace."""
        from harnessbox.names import generate_workspace_name

        return {"name": generate_workspace_name()}

    def _convert_ssh_to_https(url: str) -> str:
        """
        Convert SSH URLs to HTTPS URLs for git clone in sandboxes.

        Handles formats:
        - git@github.com:user/repo.git -> https://github.com/user/repo.git
        - git@gitlab.com:user/repo.git -> https://gitlab.com/user/repo.git
        """
        import re

        # Match SSH format: git@host:path
        ssh_pattern = r"^git@([^:]+):(.+)$"
        match = re.match(ssh_pattern, url)
        if match:
            host, path = match.groups()
            return f"https://{host}/{path}"
        return url

    @app.get("/v1/workspace/detect")
    async def detect_workspace(path: str) -> dict[str, str]:
        """
        Detect git repo info from a local filesystem path.

        Returns remote URL, default branch, and repo name.
        Validates .git exists first (prevents path traversal).
        Converts SSH URLs to HTTPS for sandbox compatibility.
        """
        import subprocess
        from pathlib import Path

        repo_path = Path(path).expanduser().resolve()
        git_dir = repo_path / ".git"

        if not git_dir.exists():
            raise HTTPException(status_code=400, detail="Not a git repository")

        if not git_dir.is_dir():
            raise HTTPException(status_code=400, detail="Invalid git repository")

        try:
            result = subprocess.run(
                ["git", "config", "--get", "remote.origin.url"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
            remote = result.stdout.strip()
            if not remote:
                raise HTTPException(status_code=400, detail="No remote.origin.url found")
            # Convert SSH to HTTPS for sandbox compatibility
            remote = _convert_ssh_to_https(remote)
        except subprocess.CalledProcessError as exc:
            raise HTTPException(status_code=400, detail="Failed to read remote URL") from exc
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(status_code=500, detail="Git command timed out") from exc

        default_branch = "main"
        try:
            result = subprocess.run(
                ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            if result.returncode == 0:
                ref = result.stdout.strip()
                if ref.startswith("refs/remotes/origin/"):
                    default_branch = ref.replace("refs/remotes/origin/", "")
            else:
                for branch in ["main", "master"]:
                    result = subprocess.run(
                        ["git", "rev-parse", "--verify", f"refs/remotes/origin/{branch}"],
                        cwd=repo_path,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=5,
                    )
                    if result.returncode == 0:
                        default_branch = branch
                        break
        except subprocess.TimeoutExpired:
            pass

        name = repo_path.name

        return {"remote": remote, "default_branch": default_branch, "name": name}

    # ----- Session endpoints -----

    @app.post("/v1/sessions", response_model=SessionResponse, status_code=201)
    async def create_session(req: CreateSessionRequest) -> SessionResponse:
        env_vars = dict(req.env_vars)
        _inject_host_env_vars(env_vars)
        api_key = req.api_key or _extract_provider_key(req.provider, env_vars)

        security_policy = None
        if req.security_policy:
            from harnessbox.security.policy import SecurityPolicy

            security_policy = SecurityPolicy(
                denied_tools=req.security_policy.denied_tools,
                denied_bash_patterns=req.security_policy.denied_bash_patterns,
                deny_network=req.security_policy.deny_network,
                credential_guards=req.security_policy.credential_guards,
            )

        workspace = None
        if req.workspace:
            from harnessbox.workspace import GitWorkspace

            workspace = GitWorkspace(
                remote=req.workspace.remote,
                branch=req.workspace.branch,
                auth_token=req.workspace.auth_token,
                clone_depth=req.workspace.clone_depth,
                clone_dir_name=req.workspace.clone_dir_name,
                commit_on_exit=req.workspace.commit_on_exit,
            )

        session_timeout = req.session_timeout
        sandbox_timeout = req.sandbox_timeout
        if session_timeout >= sandbox_timeout:
            session_timeout = max(sandbox_timeout - 60, 0)
            logger.warning(
                "session_timeout (%d) >= sandbox_timeout (%d), clamped to %d",
                req.session_timeout,
                sandbox_timeout,
                session_timeout,
            )

        config = SessionConfig(
            provider=req.provider,
            api_key=api_key,
            harness=req.harness,
            env_vars=env_vars,
            setup_script=req.setup_script,
            cwd=req.cwd,
            timeout=sandbox_timeout,
            skip_permissions=req.skip_permissions,
            template=req.template,
            security_policy=security_policy,
            workspace=workspace,
            session_timeout=session_timeout,
        )
        try:
            info = await mgr.create_session(config, session_id=req.session_id)
        except Exception as exc:
            logger.exception("Failed to create session")
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return SessionResponse(
            session_id=info.session_id,
            harness=info.harness,
            status=info.status,
            created_at=info.created_at,
            workspace_name=info.workspace_name,
        )

    @app.get("/v1/sessions", response_model=list[SessionResponse])
    async def list_sessions() -> list[SessionResponse]:
        return [
            SessionResponse(
                session_id=s.session_id,
                harness=s.harness,
                status=s.status,
                created_at=s.created_at,
                workspace_name=s.workspace_name,
            )
            for s in mgr.list_sessions()
        ]

    @app.get("/v1/sessions/{session_id}", response_model=SessionResponse)
    async def get_session(session_id: str) -> SessionResponse:
        try:
            info = mgr.get_session(session_id)
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        return SessionResponse(
            session_id=info.session_id,
            harness=info.harness,
            status=info.status,
            created_at=info.created_at,
            workspace_name=info.workspace_name,
        )

    @app.delete("/v1/sessions/{session_id}", status_code=204)
    async def destroy_session(session_id: str) -> Response:
        try:
            await mgr.destroy_session(session_id)
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        return Response(status_code=204)

    @app.post("/v1/sessions/{session_id}/prompt")
    async def prompt_session(session_id: str, req: PromptRequest) -> EventSourceResponse:
        try:
            mgr.get_session(session_id)
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc

        async def event_generator() -> Any:
            logger.info("SSE stream started for session %s", session_id)
            event_count = 0
            try:
                async for event in mgr.prompt(session_id, req.prompt):
                    event_count += 1
                    logger.info(
                        "SSE event #%d: %s (kind=%s)",
                        event_count,
                        event.event_type,
                        event.item_kind,
                    )
                    yield {
                        "event": "message",
                        "id": str(event.sequence),
                        "data": json.dumps(event.to_dict()),
                    }
            except RuntimeError as exc:
                logger.error("Stream error for session %s: %s", session_id, exc)
                yield {
                    "event": "message",
                    "data": json.dumps({"event_type": "error", "error_message": str(exc)}),
                }
            logger.info("SSE stream ended for session %s (%d events)", session_id, event_count)
            yield {"event": "message", "data": "[DONE]"}

        return EventSourceResponse(event_generator())

    @app.get("/v1/sessions/{session_id}/events")
    async def stream_events(session_id: str, request: Request) -> EventSourceResponse:
        try:
            info = mgr.get_session(session_id)
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc

        last_event_id_str = request.headers.get("last-event-id")
        last_seq = int(last_event_id_str) if last_event_id_str else None

        async def event_generator() -> Any:
            async for event in info.sandbox.event_buffer.stream(last_seq):
                yield {
                    "event": "message",
                    "id": str(event.sequence),
                    "data": json.dumps(event.to_dict()),
                }

        return EventSourceResponse(event_generator(), ping=15)

    @app.post("/v1/sessions/{session_id}/permission")
    async def respond_permission(session_id: str, req: PermissionRequest) -> dict[str, str]:
        try:
            info = mgr.get_session(session_id)
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        agent_process = info.sandbox._agent_process
        if not agent_process:
            raise HTTPException(status_code=400, detail="No persistent agent process")
        await agent_process.respond_permission(req.request_id, req.behavior)
        return {"status": "ok"}

    return app
