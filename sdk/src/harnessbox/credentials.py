"""Host credential detection — probes for available API keys and CLI auth."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class CredentialProbe:
    """Boolean-only credential availability. Values are never exposed."""

    name: str
    available: bool


@dataclass(frozen=True)
class CredentialStatus:
    probes: list[CredentialProbe]
    timestamp: str


_ENV_VAR_PROBES: tuple[str, ...] = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "E2B_API_KEY",
    "GITHUB_TOKEN",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
)


def _probe_env_var(name: str) -> CredentialProbe:
    value = os.environ.get(name, "")
    return CredentialProbe(name=name, available=bool(value.strip()))


def _probe_gh_cli() -> CredentialProbe:
    try:
        hosts_path = Path.home() / ".config" / "gh" / "hosts.yml"
        if hosts_path.is_file() and hosts_path.stat().st_size > 0:
            content = hosts_path.read_text(encoding="utf-8")
            if "github.com" in content:
                return CredentialProbe(name="gh_cli", available=True)
        return CredentialProbe(name="gh_cli", available=False)
    except Exception:
        return CredentialProbe(name="gh_cli", available=False)


def _probe_e2b_cli() -> CredentialProbe:
    try:
        config_path = Path.home() / ".e2b" / "config.json"
        if config_path.is_file():
            data = json.loads(config_path.read_text(encoding="utf-8"))
            has_token = bool(data.get("accessToken") or data.get("teamApiKey"))
            return CredentialProbe(name="e2b_cli", available=has_token)
        return CredentialProbe(name="e2b_cli", available=False)
    except Exception:
        return CredentialProbe(name="e2b_cli", available=False)


def _probe_claude_code() -> CredentialProbe:
    try:
        claude_dir = Path.home() / ".claude"
        return CredentialProbe(name="claude_code", available=claude_dir.is_dir())
    except Exception:
        return CredentialProbe(name="claude_code", available=False)


def _probe_aws_credentials() -> CredentialProbe:
    try:
        if os.environ.get("AWS_ACCESS_KEY_ID", "").strip():
            return CredentialProbe(name="aws_credentials", available=True)
        creds_path = Path.home() / ".aws" / "credentials"
        if creds_path.is_file() and creds_path.stat().st_size > 0:
            return CredentialProbe(name="aws_credentials", available=True)
        return CredentialProbe(name="aws_credentials", available=False)
    except Exception:
        return CredentialProbe(name="aws_credentials", available=False)


def _probe_ssh_keys() -> CredentialProbe:
    try:
        ssh_dir = Path.home() / ".ssh"
        if not ssh_dir.is_dir():
            return CredentialProbe(name="ssh_keys", available=False)
        for key_file in ["id_rsa", "id_ed25519", "id_ecdsa", "id_dsa"]:
            key_path = ssh_dir / key_file
            if key_path.is_file():
                return CredentialProbe(name="ssh_keys", available=True)
        return CredentialProbe(name="ssh_keys", available=False)
    except Exception:
        return CredentialProbe(name="ssh_keys", available=False)


def _probe_git_credentials() -> CredentialProbe:
    try:
        config_path = Path.home() / ".git-credentials"
        if config_path.is_file() and config_path.stat().st_size > 0:
            return CredentialProbe(name="git_credentials", available=True)
        return CredentialProbe(name="git_credentials", available=False)
    except Exception:
        return CredentialProbe(name="git_credentials", available=False)


# --- Claude Code auth mode detection ---


def detect_claude_auth_mode() -> str | None:
    """Detect Claude Code auth mode from ~/.claude/settings.json env block.

    Returns "bedrock", "vertex", "api_key", or None.
    """
    try:
        settings_path = Path.home() / ".claude" / "settings.json"
        if not settings_path.is_file():
            return None
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        env = data.get("env", {})
        if env.get("CLAUDE_CODE_USE_BEDROCK", "").lower() in ("1", "true"):
            return "bedrock"
        if env.get("CLAUDE_CODE_USE_VERTEX", "").lower() in ("1", "true"):
            return "vertex"
    except Exception:
        pass

    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return "api_key"
    return None


def build_claude_env_vars() -> dict[str, str]:
    """Build the env vars needed to authenticate Claude Code inside a sandbox.

    Reads auth mode from ~/.claude/settings.json, then probes for the
    corresponding credentials (AWS for Bedrock, GCP for Vertex, or
    ANTHROPIC_API_KEY for direct API).
    """
    mode = detect_claude_auth_mode()
    if mode is None:
        return {}

    envs: dict[str, str] = {}

    if mode == "bedrock":
        envs["CLAUDE_CODE_USE_BEDROCK"] = "1"
        _inject_aws_creds(envs)

    elif mode == "vertex":
        envs["CLAUDE_CODE_USE_VERTEX"] = "1"
        _inject_val(envs, "CLOUD_ML_REGION")
        _inject_val(envs, "ANTHROPIC_VERTEX_PROJECT_ID")
        _inject_val(envs, "GOOGLE_APPLICATION_CREDENTIALS")

    elif mode == "api_key":
        _inject_val(envs, "ANTHROPIC_API_KEY")

    return envs


def _inject_val(envs: dict[str, str], key: str) -> None:
    val = os.environ.get(key, "").strip()
    if val:
        envs[key] = val


def _inject_aws_creds(envs: dict[str, str]) -> None:
    """Inject AWS credentials from env vars or ~/.aws/credentials + config."""
    _inject_val(envs, "AWS_ACCESS_KEY_ID")
    _inject_val(envs, "AWS_SECRET_ACCESS_KEY")
    _inject_val(envs, "AWS_SESSION_TOKEN")
    _inject_val(envs, "AWS_REGION")
    _inject_val(envs, "AWS_DEFAULT_REGION")
    _inject_val(envs, "AWS_PROFILE")

    if "AWS_ACCESS_KEY_ID" not in envs:
        _read_aws_credentials_file(envs)

    if "AWS_REGION" not in envs and "AWS_DEFAULT_REGION" not in envs:
        _read_aws_config_region(envs)


def _read_aws_credentials_file(envs: dict[str, str]) -> None:
    try:
        creds_path = Path.home() / ".aws" / "credentials"
        if not creds_path.is_file():
            return
        profile = envs.get("AWS_PROFILE", "default")
        section = f"[{profile}]"
        in_section = False
        values: dict[str, str] = {}
        for line in creds_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("["):
                if in_section:
                    break
                in_section = line == section
                continue
            if in_section and "=" in line:
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip()
        if values.get("aws_access_key_id"):
            envs.setdefault("AWS_ACCESS_KEY_ID", values["aws_access_key_id"])
        if values.get("aws_secret_access_key"):
            envs.setdefault("AWS_SECRET_ACCESS_KEY", values["aws_secret_access_key"])
        if values.get("aws_session_token"):
            envs.setdefault("AWS_SESSION_TOKEN", values["aws_session_token"])
    except Exception:
        pass


def _read_aws_config_region(envs: dict[str, str]) -> None:
    try:
        config_path = Path.home() / ".aws" / "config"
        if not config_path.is_file():
            return
        profile = envs.get("AWS_PROFILE", "default")
        target = f"[profile {profile}]" if profile != "default" else "[default]"
        in_section = False
        for line in config_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("["):
                in_section = line == target
                continue
            if in_section and line.startswith("region"):
                _, v = line.split("=", 1)
                envs["AWS_REGION"] = v.strip()
                break
    except Exception:
        pass


# --- Main detection ---


def detect_credentials() -> CredentialStatus:
    """Probe the host for available credentials.

    Returns boolean availability only — no values, paths, or source details
    are ever exposed.
    """
    probes: list[CredentialProbe] = []

    for name in _ENV_VAR_PROBES:
        try:
            probes.append(_probe_env_var(name))
        except Exception:
            probes.append(CredentialProbe(name=name, available=False))

    probes.append(_probe_gh_cli())
    probes.append(_probe_e2b_cli())
    probes.append(_probe_claude_code())
    probes.append(_probe_aws_credentials())
    probes.append(_probe_ssh_keys())
    probes.append(_probe_git_credentials())

    mode = detect_claude_auth_mode()
    probes.append(
        CredentialProbe(
            name="claude_auth_mode",
            available=mode is not None,
        )
    )

    return CredentialStatus(
        probes=probes,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
