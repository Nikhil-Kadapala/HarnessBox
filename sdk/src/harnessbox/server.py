"""HTTP/SSE transport layer for HarnessBox workspaces.

Exposes workspace management and agent event streaming over HTTP.
Install with ``pip install harnessbox[server]`` for dependencies.

    uvicorn harnessbox.server:create_app --factory --port 8000

Endpoints:
    GET    /v1/workspace/name              — generate workspace name
    GET    /v1/workspace/detect            — detect repo from path
    POST   /v1/workspaces                  — create workspace
    GET    /v1/workspaces                  — list workspaces
    GET    /v1/workspaces/{id}             — get workspace info
    DELETE /v1/workspaces/{id}             — destroy workspace
    GET    /v1/workspaces/{id}/conversations — list conversations
    POST   /v1/workspaces/{id}/prompt      — send prompt, SSE response
    GET    /v1/workspaces/{id}/events      — subscribe to live events (SSE)
    GET    /v1/workspaces/{id}/history     — stream historical events from storage
    POST   /v1/workspaces/{id}/permission  — respond to permission request
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
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

from harnessbox.lifecycle import InvalidTransitionError, WorkspaceState
from harnessbox.storage import StorageBackend
from harnessbox.workspace_manager import WorkspaceConfig, WorkspaceManager, WorkspaceNotFoundError

logging.basicConfig(level=logging.DEBUG, format="%(name)s %(levelname)s: %(message)s")
logger = logging.getLogger("harnessbox.server")

_PROVIDER_KEY_NAMES: dict[str, list[str]] = {
    "e2b": ["E2B_API_KEY", "E2B_ACCESS_TOKEN"],
}

_ENV_VAR_KEYS: tuple[str, ...] = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "E2B_API_KEY",
    "GITHUB_TOKEN",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
)


def _inject_host_env_vars(env_vars: dict[str, str]) -> None:
    """Auto-inject ALL available host credentials into the sandbox.

    1. Builds Claude Code auth environment (Bedrock, Vertex, or direct API key)
    2. Builds gcloud project/region config
    3. Injects all detected API keys from host environment
    4. User-provided env vars always take priority (not overwritten)
    """
    import os

    from harnessbox.credentials import build_claude_env_vars, build_gcloud_env_vars

    claude_envs = build_claude_env_vars()
    for k, v in claude_envs.items():
        env_vars.setdefault(k, v)

    gcloud_envs = build_gcloud_env_vars()
    for k, v in gcloud_envs.items():
        env_vars.setdefault(k, v)

    for key in _ENV_VAR_KEYS:
        if key not in env_vars:
            val = os.environ.get(key, "").strip()
            if val:
                env_vars[key] = val


def _inject_host_credential_files() -> dict[str, str]:
    """Auto-inject credential files (e.g., gcloud ADC) for sandbox use."""
    from harnessbox.credentials import build_gcloud_credential_files

    return build_gcloud_credential_files()


def _get_git_auth_token() -> str | None:
    """Resolve git auth token from GITHUB_TOKEN env var or gh CLI."""
    import os
    import subprocess

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        return token

    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return None


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
    """Request body for configuring a sandbox security policy."""

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
    """Request body for git workspace configuration (remote, branch, auth)."""

    remote: str
    branch: str = "main"
    auth_token: str | None = None
    clone_depth: int = 1  # Shallow clone by default for faster setup
    clone_dir_name: str | None = None  # Subdirectory name for clone (e.g., city name)
    commit_on_exit: bool = False


class CreateSessionRequest(BaseModel):
    """Request body for creating a new sandbox workspace session."""

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
    """Response body containing session metadata and status."""

    session_id: str
    harness: str
    status: str
    created_at: str
    workspace_name: str | None = None
    branch: str | None = None
    base_branch: str | None = None
    remote: str | None = None
    pr_url: str | None = None
    pr_number: int | None = None
    ci_status: str | None = None
    total_cost_usd: float = 0.0


class SessionStatsResponse(BaseModel):
    """Response body for workspace diff statistics."""

    insertions: int = 0
    deletions: int = 0
    commit_count: int = 0


class RenameRequest(BaseModel):
    """Request body for renaming a workspace."""

    name: str


class PRRequest(BaseModel):
    """Request body for creating a pull request from the workspace branch."""

    title: str
    body: str = ""


class PromptRequest(BaseModel):
    """Request body for sending a prompt to the agent."""

    prompt: str


class TransitionRequest(BaseModel):
    """Request body for transitioning workspace lifecycle state."""

    target_state: str


class PermissionRequest(BaseModel):
    """Request body for resolving an agent permission prompt."""

    request_id: str
    behavior: str = "allow"


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(
    *,
    manager: WorkspaceManager | None = None,
    storage: str | StorageBackend | None = None,
) -> FastAPI:
    """Create a FastAPI app with optional persistent storage.

    Args:
        manager: Existing WorkspaceManager instance (or None to create).
        storage: Storage backend name ("memory", "sqlite") or instance.
                 If None, sessions are in-memory only (lost on restart).

    Returns:
        FastAPI app ready to run with uvicorn.

    Example:
        >>> app = create_app(storage="sqlite")
        >>> # OR
        >>> from harnessbox._storage import get_storage_backend
        >>> backend_cls = get_storage_backend("sqlite")
        >>> storage = backend_cls(path="~/.harnessbox/sessions.db")
        >>> app = create_app(storage=storage)
    """
    # Resolve storage backend by name if string
    resolved_storage: StorageBackend | None = None
    if isinstance(storage, str):
        from harnessbox._storage import get_storage_backend

        backend_cls = get_storage_backend(storage)
        resolved_storage = backend_cls()
    elif storage is not None:
        resolved_storage = storage

    # If manager provided, use it; otherwise create one with storage
    if manager is not None:
        mgr = manager
    else:
        # Create manager synchronously, initialize in lifespan
        mgr = WorkspaceManager(storage=resolved_storage)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        # Initialize storage and load sessions
        if mgr._storage:
            await mgr._storage.initialize()
            await mgr.load_sessions()
            logger.info("Storage initialized and sessions loaded")

        yield

        # Shutdown: close storage
        if mgr._storage:
            await mgr._storage.close()
            logger.info("Storage closed")

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

    @app.post("/v1/workspaces", response_model=SessionResponse, status_code=201)
    async def create_session(req: CreateSessionRequest) -> SessionResponse:
        env_vars = dict(req.env_vars)
        _inject_host_env_vars(env_vars)
        logger.info("Injected env vars: %s", list(env_vars.keys()))
        credential_files: dict[str, str | Path] = dict(_inject_host_credential_files())
        if "/root/.config/gcloud/application_default_credentials.json" in credential_files:
            env_vars.setdefault(
                "GOOGLE_APPLICATION_CREDENTIALS",
                "/root/.config/gcloud/application_default_credentials.json",
            )
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
            from harnessbox.names import generate_workspace_name
            from harnessbox.workspace import GitWorkspace

            clone_dir_name = req.workspace.clone_dir_name
            if clone_dir_name is None:
                clone_dir_name = generate_workspace_name()

            # Default working branch to the city name, branching off the base
            base_branch = req.workspace.branch
            branch = clone_dir_name if base_branch == "main" else base_branch

            # Auto-inject git auth token if not provided
            auth_token = req.workspace.auth_token
            if not auth_token:
                auth_token = _get_git_auth_token()

            workspace = GitWorkspace(
                remote=req.workspace.remote,
                branch=branch,
                base_branch=base_branch,
                auth_token=auth_token,
                clone_depth=req.workspace.clone_depth,
                clone_dir_name=clone_dir_name,
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

        config = WorkspaceConfig(
            provider=req.provider,
            api_key=api_key,
            harness=req.harness,
            env_vars=env_vars,
            files=credential_files or None,
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
            info = await mgr.create_workspace(config, workspace_id=req.session_id)
        except Exception as exc:
            logger.exception("Failed to create session")
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return _session_response(info)

    def _session_response(info: Any) -> SessionResponse:
        return SessionResponse(
            session_id=info.workspace_id,
            harness=info.harness,
            status=info.status,
            created_at=info.created_at,
            workspace_name=info.workspace_name,
            branch=info.branch,
            base_branch=info.base_branch,
            remote=info.remote,
            pr_url=info.pr_url,
            pr_number=info.pr_number,
            ci_status=info.ci_status,
            total_cost_usd=info.total_cost_usd,
        )

    @app.get("/v1/workspaces", response_model=list[SessionResponse])
    async def list_sessions() -> list[SessionResponse]:
        return [_session_response(s) for s in mgr.list_workspaces()]

    @app.get("/v1/workspaces/{session_id}", response_model=SessionResponse)
    async def get_session(session_id: str) -> SessionResponse:
        try:
            info = mgr.get_workspace(session_id)
        except WorkspaceNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        return _session_response(info)

    @app.delete("/v1/workspaces/{session_id}", status_code=204)
    async def destroy_session(session_id: str) -> Response:
        try:
            await mgr.destroy_workspace(session_id)
        except WorkspaceNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        return Response(status_code=204)

    @app.get("/v1/workspaces/{session_id}/conversations")
    async def list_conversations(session_id: str) -> dict[str, Any]:
        """List conversations for a workspace."""
        try:
            mgr.get_workspace(session_id)
        except WorkspaceNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc

        if mgr._storage:
            conversations = await mgr._storage.get_conversations(workspace_id=session_id)
            return {"conversations": conversations}
        return {"conversations": []}

    @app.post("/v1/workspaces/{session_id}/pause", response_model=SessionResponse)
    async def pause_session(session_id: str) -> SessionResponse:
        try:
            info = mgr.get_workspace(session_id)
        except WorkspaceNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc

        if info.status not in ("active", "streaming"):
            raise HTTPException(
                status_code=409, detail=f"Cannot pause session in state: {info.status}"
            )

        try:
            # Only call sandbox.pause() if not already paused at sandbox level
            if info.sandbox._state == WorkspaceState.ACTIVE:
                # Stop agent process before pausing sandbox
                if info.sandbox._agent_process:
                    try:
                        await info.sandbox._agent_process.stop()
                    except Exception:
                        pass
                    info.sandbox._agent_process = None
                # Pause sandbox and store ID for resume
                info.sandbox._paused_sandbox_id = await info.sandbox.pause()
            info.status = WorkspaceState.PAUSED.value
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        return _session_response(info)

    @app.post("/v1/workspaces/{session_id}/resume", response_model=SessionResponse)
    async def resume_session(session_id: str) -> SessionResponse:
        try:
            info = mgr.get_workspace(session_id)
        except WorkspaceNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc

        if info.status != "paused":
            raise HTTPException(
                status_code=409, detail=f"Cannot resume session in state: {info.status}"
            )

        # Set status to active. The actual sandbox resume + agent restart
        # happens lazily in _ensure_agent_ready() on the next prompt.
        info.status = WorkspaceState.ACTIVE.value
        return _session_response(info)

    @app.post("/v1/workspaces/{session_id}/stop", status_code=204)
    async def stop_session(session_id: str) -> Response:
        try:
            info = mgr.get_workspace(session_id)
        except WorkspaceNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc

        await info.sandbox.kill()
        info.status = WorkspaceState.FAILED.value
        return Response(status_code=204)

    @app.post("/v1/workspaces/{session_id}/rename", response_model=SessionResponse)
    async def rename_session(session_id: str, req: RenameRequest) -> SessionResponse:
        try:
            info = mgr.get_workspace(session_id)
        except WorkspaceNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc

        workspace = info.sandbox._workspace
        if workspace and hasattr(workspace, "rename_branch"):
            try:
                from harnessbox.workspace import GitWorkspace

                assert isinstance(workspace, GitWorkspace)
                provider = info.sandbox.provider
                ws_root = info.sandbox._harness_config.workspace_root
                await workspace.rename_branch(provider, ws_root, req.name)
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc

        info.branch = req.name
        info.workspace_name = req.name
        return _session_response(info)

    @app.post("/v1/workspaces/{session_id}/pr", response_model=SessionResponse)
    async def create_pr(session_id: str, req: PRRequest) -> SessionResponse:
        try:
            info = mgr.get_workspace(session_id)
        except WorkspaceNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc

        workspace = info.sandbox._workspace
        if not workspace or not hasattr(workspace, "create_pr"):
            raise HTTPException(status_code=400, detail="Session has no git workspace")

        try:
            from harnessbox.workspace import GitWorkspace

            assert isinstance(workspace, GitWorkspace)
            provider = info.sandbox.provider
            ws_root = info.sandbox._harness_config.workspace_root
            result = await workspace.create_pr(provider, ws_root, req.title, req.body)
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        info.pr_url = result.get("url")
        # Transition to in_review
        try:
            mgr.transition_workspace(session_id, "in_review")
        except Exception:
            pass

        return _session_response(info)

    @app.post("/v1/workspaces/{session_id}/pr/refresh", response_model=SessionResponse)
    async def refresh_pr_status(session_id: str) -> SessionResponse:
        try:
            info = mgr.get_workspace(session_id)
        except WorkspaceNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc

        workspace = info.sandbox._workspace
        if not workspace or not hasattr(workspace, "check_pr_status") or not info.pr_url:
            return _session_response(info)

        try:
            from harnessbox.workspace import GitWorkspace

            assert isinstance(workspace, GitWorkspace)
            provider = info.sandbox.provider
            ws_root = info.sandbox._harness_config.workspace_root
            pr_data = await workspace.check_pr_status(provider, ws_root)
        except Exception:
            logger.debug("Failed to check PR status for session %s", session_id, exc_info=True)
            return _session_response(info)

        if pr_data:
            info.ci_status = pr_data.get("ci_status")
            info.pr_number = pr_data.get("number")
            if pr_data.get("merged"):
                try:
                    mgr.transition_workspace(session_id, "merged")
                except Exception:
                    pass

        return _session_response(info)

    _NON_PROMPTABLE = frozenset({"merged", "failed", "archived", "ended", "backlog", "ending"})

    @app.post("/v1/workspaces/{session_id}/transition", response_model=SessionResponse)
    async def transition_session(session_id: str, req: TransitionRequest) -> SessionResponse:
        try:
            info = mgr.get_workspace(session_id)
        except WorkspaceNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc

        try:
            WorkspaceState(req.target_state)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=f"Unknown state: {req.target_state}"
            ) from exc

        try:
            info = mgr.transition_workspace(session_id, req.target_state)
        except InvalidTransitionError as exc:
            raise HTTPException(
                status_code=409,
                detail=f"Invalid transition: {exc.current.value} → {exc.target.value}",
            ) from exc

        return _session_response(info)

    @app.get("/v1/workspaces/{session_id}/stats", response_model=SessionStatsResponse)
    async def get_session_stats(session_id: str) -> SessionStatsResponse:
        try:
            info = mgr.get_workspace(session_id)
        except WorkspaceNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc

        workspace = info.sandbox._workspace
        if not workspace or not hasattr(workspace, "diff_stat"):
            return SessionStatsResponse()

        try:
            from harnessbox.workspace import GitWorkspace

            assert isinstance(workspace, GitWorkspace)
            provider = info.sandbox.provider
            ws_root = info.sandbox._harness_config.workspace_root
            diff = await workspace.diff_stat(provider, ws_root)
            commits = await workspace.commit_count(provider, ws_root)
        except Exception:
            logger.debug("Failed to fetch stats for session %s", session_id, exc_info=True)
            return SessionStatsResponse()

        return SessionStatsResponse(
            insertions=diff["insertions"],
            deletions=diff["deletions"],
            commit_count=commits,
        )

    @app.post("/v1/workspaces/{session_id}/prompt")
    async def prompt_session(session_id: str, req: PromptRequest) -> EventSourceResponse:
        try:
            info = mgr.get_workspace(session_id)
        except WorkspaceNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc

        if info.status in _NON_PROMPTABLE:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "SESSION_NOT_ACTIVE",
                    "status": info.status,
                    "message": "This session cannot accept prompts in its current state.",
                },
            )

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

    @app.get("/v1/workspaces/{session_id}/events")
    async def stream_events(session_id: str, request: Request) -> EventSourceResponse:
        """Subscribe to live events from an active session (SSE)."""
        try:
            info = mgr.get_workspace(session_id)
        except WorkspaceNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc

        if info.sandbox is None:
            raise HTTPException(
                status_code=400,
                detail="Session is view-only (loaded from storage). Use GET /v1/sessions/{id}/history for historical events.",
            )

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

    @app.get("/v1/workspaces/{session_id}/history")
    async def stream_history(
        session_id: str,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> EventSourceResponse:
        """Stream historical events from storage (incremental, O(1) memory).

        Args:
            session_id: Session whose history to retrieve.
            after_sequence: Only return events with sequence > this value.
            limit: Maximum number of events to return (None = unlimited).

        Returns:
            SSE stream with NDJSON events.

        Note:
            This endpoint streams from storage, not the live ring buffer.
            For active sessions, use GET /v1/sessions/{id}/events instead.
        """
        # Check if session exists
        try:
            mgr.get_workspace(session_id)
        except WorkspaceNotFoundError:
            # Session not in memory — might still be in storage
            if not mgr._storage:
                raise HTTPException(
                    status_code=404,
                    detail="Session not found and no storage enabled",
                )

        if not mgr._storage:
            raise HTTPException(
                status_code=400,
                detail="Storage not enabled. Historical events not available.",
            )

        async def event_generator() -> Any:
            async for event_record in mgr._storage.get_events(
                session_id, after_sequence=after_sequence, limit=limit
            ):
                # Deserialize event_json
                try:
                    event_data = json.loads(event_record["event_json"])
                    yield {
                        "event": "message",
                        "id": str(event_record["sequence"]),
                        "data": json.dumps(event_data),
                    }
                except json.JSONDecodeError as e:
                    logger.error(f"Malformed event_json for event {event_record['event_id']}: {e}")

        return EventSourceResponse(event_generator(), ping=15)

    @app.post("/v1/workspaces/{session_id}/permission")
    async def respond_permission(session_id: str, req: PermissionRequest) -> dict[str, str]:
        try:
            info = mgr.get_workspace(session_id)
        except WorkspaceNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        agent_process = info.sandbox._agent_process
        if not agent_process:
            raise HTTPException(status_code=400, detail="No persistent agent process")
        await agent_process.respond_permission(req.request_id, req.behavior)
        return {"status": "ok"}

    return app
