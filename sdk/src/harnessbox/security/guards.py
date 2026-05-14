"""Credential guard catalog — composable, provider-specific security patterns.

Each guard set covers one provider's secrets: env vars, credential files,
config directories, metadata endpoints, and CLI commands that fetch credentials.

Both settings.json deny rules and the PreToolUse hook script derive from
these guard sets. This is the single source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CredentialGuardSet:
    """A named set of credential protection patterns.

    Attributes:
        name: Identifier for this guard set (e.g. "aws", "gcp").
        bash_deny_globs: Glob patterns for settings.json permissions.deny.Bash.
        read_deny_globs: Glob patterns for settings.json permissions.deny.Read.
        hook_regexes: Regex pattern strings for the PreToolUse hook script.
    """

    name: str
    bash_deny_globs: tuple[str, ...] = ()
    read_deny_globs: tuple[str, ...] = ()
    hook_regexes: tuple[str, ...] = ()

    def render_settings_deny(self) -> dict[str, list[str]]:
        """Render this guard set's deny rules for settings.json."""
        return {
            "Bash": list(self.bash_deny_globs),
            "Read": list(self.read_deny_globs),
        }

    def render_hook_lines(self) -> list[str]:
        """Render this guard set's regexes as Python source lines for the hook script."""
        lines = []
        for regex in self.hook_regexes:
            escaped = regex.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'    r"{escaped}",')
        return lines


# ---------------------------------------------------------------------------
# CORE — always included when any credential guards are active
# ---------------------------------------------------------------------------

CORE = CredentialGuardSet(
    name="core",
    bash_deny_globs=(
        "env",
        "env *",
        "printenv",
        "printenv *",
        "export -p",
        "export -p *",
        "set",
        "compgen -e",
        "compgen -e *",
        "cat /proc/*/environ",
        "cat /proc/self/environ",
        "strings /proc/*/environ",
        "xargs -0 < /proc/*/environ",
    ),
    read_deny_globs=(
        ".env",
        ".env.*",
        "**/.env",
        "**/.env.*",
        ".claude/settings.json",
        ".claude/settings.local.json",
        ".git/config",
        ".git-credentials",
        "~/.git-credentials",
    ),
    hook_regexes=(
        r"\benv\b",
        r"\bprintenv\b",
        r"\bexport\s+-p\b",
        r"\bset\b(?=\s*$|\s*\|)",
        r"\bcompgen\s+-e\b",
        r"os\.environ",
        r"os\.getenv",
        r"/proc/\S*/environ",
        r"/proc/self/environ",
        r"\.claude/settings\.local\.json",
        r"git\s+config\s+credential\.helper",
        r"\.git-credentials",
    ),
)

# ---------------------------------------------------------------------------
# AWS
# ---------------------------------------------------------------------------

AWS = CredentialGuardSet(
    name="aws",
    bash_deny_globs=(
        "cat ~/.aws/credentials",
        "cat ~/.aws/config",
        "curl http://169.254.169.254/*",
        "wget http://169.254.169.254/*",
        "curl http://169.254.170.2/*",
        "wget http://169.254.170.2/*",
        "aws sts get-caller-identity*",
        "aws sts assume-role*",
        "aws configure*",
    ),
    read_deny_globs=(
        "~/.aws/credentials",
        "~/.aws/config",
        "~/.aws/cli/cache/*",
        "~/.aws/sso/cache/*",
    ),
    hook_regexes=(
        r"\$AWS_SECRET_ACCESS_KEY",
        r"\$AWS_ACCESS_KEY_ID",
        r"\$AWS_SESSION_TOKEN",
        r"\$AWS_CONTAINER_CREDENTIALS",
        r"\$\{?AWS_SECRET",
        r"\$\{?AWS_ACCESS",
        r"\$AWS_WEB_IDENTITY_TOKEN_FILE",
        r"\$AWS_SHARED_CREDENTIALS_FILE",
        r"\$AWS_CONFIG_FILE",
        r"\.aws/credentials",
        r"\.aws/config",
        r"\.aws/cli/cache",
        r"\.aws/sso/cache",
        r"169\.254\.169\.254",
        r"169\.254\.170\.2",
    ),
)

# ---------------------------------------------------------------------------
# GCP / Vertex AI / Gemini
# ---------------------------------------------------------------------------

GCP = CredentialGuardSet(
    name="gcp",
    bash_deny_globs=(
        "cat ~/.config/gcloud/application_default_credentials.json",
        "cat ~/.config/gcloud/credentials.db",
        "cat ~/.config/gcloud/properties",
        "curl http://metadata.google.internal/*",
        "wget http://metadata.google.internal/*",
        "gcloud auth print-access-token*",
        "gcloud auth application-default*",
        "gcloud auth print-identity-token*",
        "gcloud secrets versions access*",
    ),
    read_deny_globs=(
        "~/.config/gcloud/application_default_credentials.json",
        "~/.config/gcloud/credentials.db",
        "~/.config/gcloud/properties",
        "~/.config/gcloud/access_tokens.db",
        "~/.config/gcloud/configurations/*",
        "**/service-account-*.json",
        "**/*-credentials.json",
    ),
    hook_regexes=(
        r"\$GOOGLE_APPLICATION_CREDENTIALS",
        r"\$\{?GOOGLE_APPLICATION_CREDENTIALS",
        r"\$GOOGLE_API_KEY",
        r"\$\{?GOOGLE_API_KEY",
        r"\$GEMINI_API_KEY",
        r"\$\{?GEMINI_API_KEY",
        r"\$VERTEX_AI_API_KEY",
        r"\$\{?VERTEX_AI_API_KEY",
        r"\$GOOGLE_GENAI_API_KEY",
        r"\$\{?GOOGLE_GENAI_API_KEY",
        r"\$CLOUDSDK_CONFIG",
        r"\$GCLOUD_CONFIG",
        r"\$CLOUD_ML_PROJECT_ID",
        r"\.config/gcloud/application_default_credentials",
        r"\.config/gcloud/credentials\.db",
        r"\.config/gcloud/access_tokens\.db",
        r"metadata\.google\.internal",
        r"gcloud\s+auth\s+print-access-token",
        r"gcloud\s+auth\s+print-identity-token",
        r"gcloud\s+secrets\s+versions\s+access",
    ),
)

# ---------------------------------------------------------------------------
# Azure
# ---------------------------------------------------------------------------

AZURE = CredentialGuardSet(
    name="azure",
    bash_deny_globs=(
        "cat ~/.azure/accessTokens.json",
        "cat ~/.azure/msal_token_cache.json",
        "cat ~/.azure/azureProfile.json",
        "curl http://169.254.169.254/metadata/identity/*",
        "wget http://169.254.169.254/metadata/identity/*",
        "curl http://168.63.129.16/*",
        "wget http://168.63.129.16/*",
        "az account get-access-token*",
        "az login*",
    ),
    read_deny_globs=(
        "~/.azure/accessTokens.json",
        "~/.azure/msal_token_cache.json",
        "~/.azure/azureProfile.json",
        "~/.azure/credentials",
    ),
    hook_regexes=(
        r"\$AZURE_CLIENT_SECRET",
        r"\$\{?AZURE_CLIENT_SECRET",
        r"\$AZURE_CLIENT_ID",
        r"\$AZURE_TENANT_ID",
        r"\$AZURE_SUBSCRIPTION_ID",
        r"\$AZURE_FEDERATED_TOKEN_FILE",
        r"\$MSI_ENDPOINT",
        r"\$MSI_SECRET",
        r"\$IDENTITY_ENDPOINT",
        r"\$IDENTITY_HEADER",
        r"\.azure/accessTokens\.json",
        r"\.azure/msal_token_cache",
        r"\.azure/azureProfile",
        r"168\.63\.129\.16",
        r"az\s+account\s+get-access-token",
    ),
)

# ---------------------------------------------------------------------------
# SSH
# ---------------------------------------------------------------------------

SSH = CredentialGuardSet(
    name="ssh",
    bash_deny_globs=(
        "cat ~/.ssh/id_rsa",
        "cat ~/.ssh/id_ed25519",
        "cat ~/.ssh/id_ecdsa",
        "cat ~/.ssh/config",
    ),
    read_deny_globs=(
        "~/.ssh/id_rsa",
        "~/.ssh/id_ed25519",
        "~/.ssh/id_ecdsa",
        "~/.ssh/id_dsa",
        "~/.ssh/config",
        "~/.ssh/authorized_keys",
        "~/.gnupg/*",
    ),
    hook_regexes=(
        r"\.ssh/id_rsa",
        r"\.ssh/id_ed25519",
        r"\.ssh/id_ecdsa",
        r"\.ssh/id_dsa",
        r"\$SSH_AUTH_SOCK",
        r"\$SSH_PRIVATE_KEY",
    ),
)

# ---------------------------------------------------------------------------
# Docker
# ---------------------------------------------------------------------------

DOCKER = CredentialGuardSet(
    name="docker",
    bash_deny_globs=("cat ~/.docker/config.json",),
    read_deny_globs=(
        "~/.docker/config.json",
        "/var/run/docker.sock",
    ),
    hook_regexes=(
        r"\.docker/config\.json",
        r"/var/run/docker\.sock",
        r"\$DOCKER_AUTH_CONFIG",
        r"\$\{?DOCKER_AUTH_CONFIG",
        r"\$DOCKER_CONFIG",
    ),
)

# ---------------------------------------------------------------------------
# Kubernetes
# ---------------------------------------------------------------------------

KUBERNETES = CredentialGuardSet(
    name="kubernetes",
    bash_deny_globs=(
        "cat ~/.kube/config",
        "cat /var/run/secrets/kubernetes.io/serviceaccount/token",
    ),
    read_deny_globs=(
        "~/.kube/config",
        "~/.kube/cache/*",
        "/var/run/secrets/kubernetes.io/serviceaccount/token",
        "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt",
    ),
    hook_regexes=(
        r"\.kube/config",
        r"/var/run/secrets/kubernetes\.io",
        r"\$KUBECONFIG",
        r"\$\{?KUBECONFIG",
    ),
)

# ---------------------------------------------------------------------------
# Databases
# ---------------------------------------------------------------------------

DATABASES = CredentialGuardSet(
    name="databases",
    bash_deny_globs=(),
    read_deny_globs=(),
    hook_regexes=(
        r"\$DATABASE_URL",
        r"\$\{?DATABASE_URL",
        r"\$DB_URL",
        r"\$REDIS_URL",
        r"\$REDIS_PASSWORD",
        r"\$MONGO_URI",
        r"\$MONGODB_URI",
        r"\$POSTGRES_PASSWORD",
        r"\$PGPASSWORD",
        r"\$MYSQL_PASSWORD",
        r"\$MYSQL_ROOT_PASSWORD",
        r"postgres(ql)?://\S+:\S+@",
        r"mysql://\S+:\S+@",
        r"mongodb(\+srv)?://\S+:\S+@",
        r"redis(s)?://\S+:\S+@",
    ),
)

# ---------------------------------------------------------------------------
# Package Managers
# ---------------------------------------------------------------------------

PACKAGE_MANAGERS = CredentialGuardSet(
    name="package_managers",
    bash_deny_globs=(
        "cat ~/.npmrc",
        "cat ~/.pypirc",
        "cat ~/.gem/credentials",
        "cat ~/.cargo/credentials.toml",
    ),
    read_deny_globs=(
        "~/.npmrc",
        "~/.yarnrc",
        "~/.yarnrc.yml",
        "~/.pypirc",
        "~/.gem/credentials",
        "~/.cargo/credentials.toml",
        "~/.nuget/NuGet.Config",
    ),
    hook_regexes=(
        r"\.npmrc",
        r"\.pypirc",
        r"\.gem/credentials",
        r"\.cargo/credentials",
        r"\$NPM_TOKEN",
        r"\$\{?NPM_TOKEN",
        r"\$PYPI_TOKEN",
    ),
)

# ---------------------------------------------------------------------------
# LLM Providers
# ---------------------------------------------------------------------------

LLM_PROVIDERS = CredentialGuardSet(
    name="llm_providers",
    bash_deny_globs=(),
    read_deny_globs=(),
    hook_regexes=(
        r"\$OPENAI_API_KEY",
        r"\$\{?OPENAI_API_KEY",
        r"\$ANTHROPIC_API_KEY",
        r"\$\{?ANTHROPIC_API_KEY",
        r"\$REPLICATE_API_TOKEN",
        r"\$COHERE_API_KEY",
        r"\$TOGETHER_API_KEY",
        r"\$FIREWORKS_API_KEY",
        r"\$GROQ_API_KEY",
        r"\$MISTRAL_API_KEY",
        r"\$DEEPSEEK_API_KEY",
        r"\$HUGGING_FACE_HUB_TOKEN",
        r"\$\{?HUGGING_FACE_HUB_TOKEN",
        r"\$EXA_API_KEY",
        r"\$\{?EXA_API_KEY",
    ),
)

# ---------------------------------------------------------------------------
# Generic — wildcard patterns for any secret-like env var
# ---------------------------------------------------------------------------

GENERIC = CredentialGuardSet(
    name="generic",
    bash_deny_globs=(),
    read_deny_globs=(),
    hook_regexes=(
        r"\$[A-Z_]*SECRET[A-Z_]*",
        r"\$\{[A-Z_]*SECRET[A-Z_]*\}",
        r"\$[A-Z_]*TOKEN[A-Z_]*",
        r"\$\{[A-Z_]*TOKEN[A-Z_]*\}",
        r"\$[A-Z_]*API_KEY",
        r"\$\{[A-Z_]*API_KEY\}",
        r"\$[A-Z_]*PASSWORD",
        r"\$\{[A-Z_]*PASSWORD\}",
        r"\$[A-Z_]*CREDENTIALS",
        r"\$\{[A-Z_]*CREDENTIALS\}",
    ),
)

# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

GUARD_CATALOG: dict[str, CredentialGuardSet] = {
    gs.name: gs
    for gs in [
        AWS,
        GCP,
        AZURE,
        SSH,
        DOCKER,
        KUBERNETES,
        DATABASES,
        PACKAGE_MANAGERS,
        LLM_PROVIDERS,
        GENERIC,
    ]
}

ALL_GUARD_NAMES: frozenset[str] = frozenset(GUARD_CATALOG.keys())


def merge_guard_sets(
    names: frozenset[str],
    *,
    extra_bash_guards: tuple[str, ...] = (),
    extra_read_guards: tuple[str, ...] = (),
    extra_hook_regexes: tuple[str, ...] = (),
) -> CredentialGuardSet:
    """Merge CORE + selected guard sets into a single composite.

    Deduplicates patterns while preserving order. CORE is always first.
    """
    all_bash: list[str] = []
    all_read: list[str] = []
    all_hook: list[str] = []

    def _extend(target: list[str], source: tuple[str, ...]) -> None:
        for p in source:
            if p not in target:
                target.append(p)

    _extend(all_bash, CORE.bash_deny_globs)
    _extend(all_read, CORE.read_deny_globs)
    _extend(all_hook, CORE.hook_regexes)

    for name in sorted(names):
        if name not in GUARD_CATALOG:
            raise KeyError(
                f"Unknown credential guard set {name!r}. "
                f"Valid sets: {', '.join(sorted(GUARD_CATALOG))}"
            )
        gs = GUARD_CATALOG[name]
        _extend(all_bash, gs.bash_deny_globs)
        _extend(all_read, gs.read_deny_globs)
        _extend(all_hook, gs.hook_regexes)

    _extend(all_bash, extra_bash_guards)
    _extend(all_read, extra_read_guards)
    _extend(all_hook, extra_hook_regexes)

    return CredentialGuardSet(
        name="merged",
        bash_deny_globs=tuple(all_bash),
        read_deny_globs=tuple(all_read),
        hook_regexes=tuple(all_hook),
    )
