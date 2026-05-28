"""Workspace configuration factory — server-specific config construction.

Consolidates credential injection, git auth resolution, provider key extraction,
and workspace naming logic that transforms an HTTP request into a fully-resolved
WorkspaceConfig for WorkspaceRegistry.create_workspace().
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
    from harnessbox._server.routers._models import CreateSessionRequest

from harnessbox._server.registry import WorkspaceConfig

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
    """Auto-inject ALL available host credentials into the sandbox.

    1. Builds Claude Code auth environment (Bedrock, Vertex, or direct API key)
    2. Builds gcloud project/region config
    3. Injects all detected API keys from host environment
    4. User-provided env vars always take priority (not overwritten)
    """
    from harnessbox.credentials import build_claude_env_vars, build_gcloud_env_vars

    claude_envs = build_claude_env_vars()
    for k, v in claude_envs.items():
        env_vars.setdefault(k, v)

    gcloud_envs = build_gcloud_env_vars()
    for k, v in gcloud_envs.items():
        env_vars.setdefault(k, v)

    for key in ENV_VAR_KEYS:
        if key not in env_vars:
            val = os.environ.get(key, "").strip()
            if val:
                env_vars[key] = val


def inject_host_credential_files() -> dict[str, str]:
    """Auto-inject credential files (e.g., gcloud ADC) for sandbox use."""
    from harnessbox.credentials import build_gcloud_credential_files

    return build_gcloud_credential_files()


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
    """Convert SSH URLs to HTTPS URLs for git clone in sandboxes.

    Handles formats:
    - git@github.com:user/repo.git -> https://github.com/user/repo.git
    - git@gitlab.com:user/repo.git -> https://gitlab.com/user/repo.git
    """
    ssh_pattern = r"^git@([^:]+):(.+)$"
    match = re.match(ssh_pattern, url)
    if match:
        host, path = match.groups()
        return f"https://{host}/{path}"
    return url


def build_workspace_config(req: CreateSessionRequest) -> WorkspaceConfig:
    """Transform an HTTP CreateSessionRequest into a fully-resolved WorkspaceConfig.

    Handles: credential injection, git auth resolution, security policy construction,
    workspace naming, and timeout clamping.
    """
    from harnessbox.security.policy import SecurityPolicy

    env_vars = dict(req.env_vars)
    inject_host_env_vars(env_vars)
    logger.info("Injected env vars: %s", list(env_vars.keys()))

    credential_files: dict[str, str | Path] = dict(inject_host_credential_files())
    if "/root/.config/gcloud/application_default_credentials.json" in credential_files:
        env_vars.setdefault(
            "GOOGLE_APPLICATION_CREDENTIALS",
            "/root/.config/gcloud/application_default_credentials.json",
        )

    api_key = req.api_key or extract_provider_key(req.provider, env_vars)

    security_policy = None
    if req.security_policy:
        security_policy = SecurityPolicy(
            denied_tools=req.security_policy.denied_tools,
            denied_bash_patterns=req.security_policy.denied_bash_patterns,
            deny_network=req.security_policy.deny_network,
            credential_guards=req.security_policy.credential_guards,
        )

    workspace = None
    if req.workspace:
        from harnessbox.names import generate_workspace_name
        from harnessbox.workspace import GitRepoConfig

        clone_dir_name = req.workspace.clone_dir_name
        if clone_dir_name is None:
            clone_dir_name = generate_workspace_name()

        base_branch = req.workspace.branch
        branch = clone_dir_name if base_branch == "main" else base_branch

        auth_token = req.workspace.auth_token
        if not auth_token:
            auth_token = get_git_auth_token()

        workspace = GitRepoConfig(
            remote=req.workspace.remote,
            branch=branch,
            base_branch=base_branch,
            auth_token=auth_token,
            clone_depth=req.workspace.clone_depth,
            clone_dir_name=clone_dir_name,
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

    return WorkspaceConfig(
        provider=req.provider,
        api_key=api_key,
        harness="claude-code",
        model=req.model,
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
