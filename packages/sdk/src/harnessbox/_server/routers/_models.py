"""Pydantic request/response models for the HarnessBox HTTP API."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator


class GitCredentials(BaseModel):
    """How to authenticate with a git remote.

    ``type=ssh`` / ``ssh_key`` are accepted on the wire but not yet wired into
    clone auth (token / gh only). Prefer ``type=token`` or ``type=gh``.
    """

    type: str = "token"
    """Auth method: ``token``, ``gh``, or ``ssh``."""

    token: str | None = None
    """Personal access token or equivalent (for ``type=token``)."""

    ssh_key: str | None = None
    """Private SSH key material (for ``type=ssh``). Unused until SSH auth lands."""


class GitSourceParams(BaseModel):
    """Git repository to clone during workspace create."""

    repo_url: str
    branch: str = "main"
    credentials: GitCredentials | None = None
    clone_depth: int = 1
    clone_dir_name: str | None = None


class FileSystemParams(BaseModel):
    """Filesystem or remote volume to attach during workspace create."""

    source: str
    mount_path: str = "/workspace"
    """Path inside the sandbox where the volume is attached."""


class CreateWorkspaceRequestParams(BaseModel):
    """Request body for ``POST /v1/workspaces/create``.

    Identity fields (``workspace_id``, ``project_id``, ``model``) are not
    accepted — the server mints ``workspace_id``; ``project_id`` stays null
    until a Project API exists; model belongs on a future session/configure path.
    ``harness`` selects the agent type stored on the workspace (default
    ``claude-code`` when omitted).
    """

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
    git: GitSourceParams | None = None
    file_system: FileSystemParams | None = None


class CreateWorkspaceResponseParams(BaseModel):
    """Response body for workspace create/list/get/lifecycle endpoints."""

    workspace_id: str
    state: str
    created_at: str
    harness: str = "claude-code"
    project_id: str | None = None
    workspace_name: str | None = None
    branch: str | None = None
    base_branch: str | None = None
    remote: str | None = None
    file_system_path: str | None = None
    total_cost_usd: float = 0.0
    error_message: str | None = None


class UploadFileParams(BaseModel):
    """Upload a file into an existing workspace sandbox."""

    path: str
    """Absolute path inside the sandbox (e.g. ``/workspace/notes.md``)."""

    content: str | None = None
    """UTF-8 text content. Mutually exclusive with ``content_b64``."""

    content_b64: str | None = Field(default=None, max_length=14_000_000)
    """Base64-encoded binary content. Mutually exclusive with ``content``."""

    @model_validator(mode="after")
    def _require_content(self) -> UploadFileParams:
        if self.content is None and self.content_b64 is None:
            raise ValueError("Provide content or content_b64")
        if self.content is not None and self.content_b64 is not None:
            raise ValueError("Provide only one of content or content_b64")
        return self


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


# ---------------------------------------------------------------------------
# Deprecated aliases (pre-workspace-API-unify). Prefer *Params names above.
# ---------------------------------------------------------------------------

# Back-compat type aliases for older imports
GitCredentialsParams = GitCredentials
MountSourceParams = FileSystemParams


class SecurityPolicyRequest(BaseModel):
    """Deprecated — configure belongs on a future endpoint, not create."""

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
    """Deprecated — use GitSourceParams."""

    remote: str
    branch: str = "main"
    auth_token: str | None = None
    clone_depth: int = 1
    clone_dir_name: str | None = None


class CreateSessionRequest(BaseModel):
    """Deprecated alias accepting the legacy create body shape.

    Prefer :class:`CreateWorkspaceRequestParams`. Still accepted so older
    clients can migrate; mapped to the new shape in the factory. Client-supplied
    ``session_id`` / ``workspace_id`` / ``project_id`` / ``model`` are ignored
    at the HTTP boundary (server mints identity).
    """

    provider: str = "e2b"
    api_key: str | None = None
    harness: str = "claude-code"
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
    project_id: str | None = None
    git: GitSourceParams | None = None
    file_system: FileSystemParams | None = None
    mount: FileSystemParams | None = None  # legacy alias for file_system
    workspace_id: str | None = None


# Response alias used by older call sites
SessionResponse = CreateWorkspaceResponseParams
WorkspaceParams = CreateWorkspaceResponseParams
