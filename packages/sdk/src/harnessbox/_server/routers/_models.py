"""Pydantic request/response models for the HarnessBox HTTP API."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


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
    clone_depth: int = 1
    clone_dir_name: str | None = None


class CreateSessionRequest(BaseModel):
    """Request body for creating a new sandbox workspace session."""

    provider: str = "e2b"
    api_key: str | None = None
    model: str | None = None
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
    """Response body containing session metadata and state."""

    session_id: str
    harness: str
    runtime_state: str
    created_at: str
    workspace_name: str | None = None
    branch: str | None = None
    base_branch: str | None = None
    remote: str | None = None
    total_cost_usd: float = 0.0
    error_message: str | None = None


class AttachmentPayload(BaseModel):
    """A single attachment in a prompt request."""

    filename: str
    mime_type: str = "application/octet-stream"
    data_b64: str = Field(max_length=14_000_000)


class PromptRequest(BaseModel):
    """Request body for sending a prompt to the agent."""

    prompt: str
    harness: str
    conversation_id: str | None = None
    attachments: list[AttachmentPayload] = []


class PermissionRequest(BaseModel):
    """Request body for resolving an agent permission prompt."""

    request_id: str
    behavior: str = "allow"
