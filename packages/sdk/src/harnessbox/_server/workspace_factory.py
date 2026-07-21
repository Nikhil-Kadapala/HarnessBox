"""Workspace configuration factory — server-specific config construction.

Transforms an HTTP create request into a fully-resolved WorkspaceConfig for
WorkspaceRegistry.create_workspace().
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from harnessbox._server.routers._models import (
        CreateSessionRequest,
        CreateWorkspaceRequestParams,
    )

from harnessbox._server.registry import WorkspaceConfig
from harnessbox.config.pipeline import FileSystemSpec

logger = logging.getLogger(__name__)

PROVIDER_KEY_NAMES: dict[str, list[str]] = {
    "e2b": ["E2B_API_KEY", "E2B_ACCESS_TOKEN"],
}

ENV_VAR_KEYS: tuple[str, ...] = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "E2B_API_KEY",
    "GITHUB_TOKEN",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
)


def inject_host_env_vars(env_vars: dict[str, str]) -> None:
    """Merge selected host env keys into the sandbox env via setdefault.

    User-provided env vars always take priority (not overwritten). Does not
    call Claude/GCP credential builders — callers must supply those explicitly
    or rely on ``ENV_VAR_KEYS`` already present on the host.
    """
    for key in ENV_VAR_KEYS:
        if key not in env_vars:
            val = os.environ.get(key, "").strip()
            if val:
                env_vars[key] = val


def inject_host_credential_files() -> dict[str, str]:
    """Deprecated — create no longer injects credential files.

    Retained so older call sites/tests import without breaking. Prefer
    file_system or upload for file-based credentials.
    """
    return {}


def get_git_auth_token() -> str | None:
    """Resolve git auth token from GITHUB_TOKEN env var or gh CLI."""
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


def extract_provider_key(provider: str, env_vars: dict[str, str]) -> str | None:
    """Resolve provider API key from: request env_vars -> host env -> CLI config files."""
    for key_name in PROVIDER_KEY_NAMES.get(provider, []):
        if key_name in env_vars:
            return env_vars[key_name]

    for key_name in PROVIDER_KEY_NAMES.get(provider, []):
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


def convert_ssh_to_https(url: str) -> str:
    """Convert SSH URLs to HTTPS URLs for git clone in sandboxes."""
    ssh_pattern = r"^git@([^:]+):(.+)$"
    match = re.match(ssh_pattern, url)
    if match:
        host, path = match.groups()
        return f"https://{host}/{path}"
    return url


def _normalize_create_request(
    req: CreateWorkspaceRequestParams | CreateSessionRequest,
) -> CreateWorkspaceRequestParams:
    """Normalize legacy CreateSessionRequest into CreateWorkspaceRequestParams."""
    from harnessbox._server.routers._models import (
        CreateSessionRequest,
        CreateWorkspaceRequestParams,
        GitCredentials,
        GitSourceParams,
    )

    if type(req).__name__ == "CreateWorkspaceRequestParams":
        return req  # type: ignore[return-value]

    # Legacy CreateSessionRequest (or hybrid body)
    git = getattr(req, "git", None)
    workspace = getattr(req, "workspace", None)
    if git is None and workspace is not None:
        creds = None
        if workspace.auth_token:
            creds = GitCredentials(type="token", token=workspace.auth_token)
        git = GitSourceParams(
            repo_url=workspace.remote,
            branch=workspace.branch,
            credentials=creds,
            clone_depth=workspace.clone_depth,
            clone_dir_name=workspace.clone_dir_name,
        )

    file_system = getattr(req, "file_system", None) or getattr(req, "mount", None)

    assert isinstance(req, CreateSessionRequest)
    return CreateWorkspaceRequestParams(
        provider=req.provider,
        api_key=req.api_key,
        env_vars=dict(req.env_vars),
        setup_script=req.setup_script,
        cwd=req.cwd,
        sandbox_timeout=req.sandbox_timeout,
        session_timeout=req.session_timeout,
        skip_permissions=req.skip_permissions,
        template=req.template,
        git=git,
        file_system=file_system,
    )


def build_workspace_config(
    req: CreateWorkspaceRequestParams | CreateSessionRequest,
) -> WorkspaceConfig:
    """Transform an HTTP create request into a fully-resolved WorkspaceConfig.

    Slim create: ENV_VAR_KEYS host merge + optional git clone and/or file_system.
    Does not write harness/agent files or host credential files. Always leaves
    ``project_id`` / ``model`` unset (null) — those belong on later APIs.
    """
    normalized = _normalize_create_request(req)

    env_vars = dict(normalized.env_vars)
    inject_host_env_vars(env_vars)
    logger.info("Injected env vars: %s", list(env_vars.keys()))

    api_key = normalized.api_key or extract_provider_key(normalized.provider, env_vars)

    workspace = None
    remote_label = ""
    branch_label = ""
    if normalized.git:
        from harnessbox.names import generate_workspace_name
        from harnessbox.workspace import GitRepoConfig

        git = normalized.git
        clone_dir_name = git.clone_dir_name
        if clone_dir_name is None:
            clone_dir_name = generate_workspace_name()

        base_branch = git.branch
        branch = clone_dir_name if base_branch == "main" else base_branch

        auth_token: str | None = None
        if git.credentials and git.credentials.token:
            auth_token = git.credentials.token
        elif git.credentials is None or git.credentials.type in ("token", "gh"):
            auth_token = get_git_auth_token()

        remote = convert_ssh_to_https(git.repo_url)
        workspace = GitRepoConfig(
            remote=remote,
            branch=branch,
            base_branch=base_branch,
            auth_token=auth_token,
            clone_depth=git.clone_depth,
            clone_dir_name=clone_dir_name,
        )
        remote_label = remote
        branch_label = branch

    file_system_spec = None
    if normalized.file_system:
        file_system_spec = FileSystemSpec(
            source=normalized.file_system.source,
            mount_path=normalized.file_system.mount_path,
        )

    session_timeout = normalized.session_timeout
    sandbox_timeout = normalized.sandbox_timeout
    if session_timeout >= sandbox_timeout:
        session_timeout = max(sandbox_timeout - 60, 0)
        logger.warning(
            "session_timeout (%d) >= sandbox_timeout (%d), clamped to %d",
            normalized.session_timeout,
            sandbox_timeout,
            session_timeout,
        )

    return WorkspaceConfig(
        provider=normalized.provider,
        api_key=api_key,
        harness="claude-code",
        model=None,
        env_vars=env_vars,
        files=None,
        setup_script=normalized.setup_script,
        cwd=normalized.cwd,
        timeout=sandbox_timeout,
        skip_permissions=normalized.skip_permissions,
        template=normalized.template,
        security_policy=None,
        workspace=workspace,
        file_system=file_system_spec,
        project_id=None,
        session_timeout=session_timeout,
        branch_label=branch_label,
        remote_label=remote_label,
    )
