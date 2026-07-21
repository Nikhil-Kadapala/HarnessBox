"""Sandbox initialization — sequential steps for provisioning a workspace VM."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from harnessbox.config.harness import HarnessTypeConfig
from harnessbox.config.manifest import SandboxManifest
from harnessbox.providers import SandboxProvider
from harnessbox.security.policy import SecurityPolicy
from harnessbox.workspace import Workspace

_log = logging.getLogger("harnessbox.pipeline")


@dataclass
class MountSpec:
    """Filesystem or remote mount to attach during initialization."""

    source: str
    mount_path: str = "/workspace"


@dataclass
class InitializeContext:
    """Mutable state carried across initialization steps.

    Each step reads from and writes to this context. The pipeline
    guarantees steps run in declaration order, so earlier writes
    are visible to later reads.
    """

    provider: SandboxProvider
    harness_config: HarnessTypeConfig
    security_policy: SecurityPolicy | None = None
    workspace: Workspace | None = None
    mount: MountSpec | None = None
    env_vars: dict[str, str] = field(default_factory=dict)
    timeout: int = 300

    # User-provided inputs (kept for future configure / power users)
    dirs: list[str] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)
    system_prompt: str | None = None
    setup_script: str | None = None

    # Whether to allow .harnessbox.toml setup_script from cloned repos
    allow_project_setup_script: bool = True

    # Snapshot-based creation (skips template)
    snapshot_id: str | None = None

    # Populated during execution (manifest kept for future configure endpoint)
    manifest: SandboxManifest | None = None
    manifest_target_dir: str = ""
    cwd: str = ""

    # Step timing records
    timings: dict[str, float] = field(default_factory=dict)


StepFn = Callable[[InitializeContext], Awaitable[None]]


@dataclass(frozen=True)
class InitializeStep:
    """A named step in the sandbox initialization sequence."""

    name: str
    execute: StepFn
    skip_if: Callable[[InitializeContext], bool] | None = None


class InitializeSandbox:
    """Sequential initializer for sandbox provisioning.

    Steps execute in declaration order. Each step receives the shared
    InitializeContext. If a step raises, executionhalts and the exception
    propagates.

    Supports dry-run (returns step names without executing) and
    per-step timing.
    """

    def __init__(self, steps: list[InitializeStep]) -> None:
        self._steps = list(steps)

    @property
    def steps(self) -> list[InitializeStep]:
        """Return the ordered list of initialization steps."""
        return list(self._steps)

    def step_names(self) -> list[str]:
        """Return ordered step names (useful for dry-run inspection)."""
        return [s.name for s in self._steps]

    async def execute(self, ctx: InitializeContext) -> dict[str, float]:
        """Run all steps sequentially, returning per-step timings.

        Steps with a ``skip_if`` predicate that returns True are skipped.
        """
        total_start = time.time()

        for step in self._steps:
            if step.skip_if and step.skip_if(ctx):
                _log.debug("Skipping step: %s", step.name)
                ctx.timings[step.name] = 0.0
                continue

            step_start = time.time()
            await step.execute(ctx)
            elapsed = time.time() - step_start
            ctx.timings[step.name] = elapsed
            _log.info("%s took %.2fs", step.name, elapsed)

        total = time.time() - total_start
        ctx.timings["_total"] = total
        _log.info("init_sandbox_total took %.2fs", total)

        return ctx.timings

    def dry_run(self, ctx: InitializeContext) -> list[str]:
        """Return step names that would execute (respecting skip_if).

        Note: skip_if predicates are evaluated against the initial context
        without running preceding steps. Predicates should only inspect
        fields set at construction time, not fields populated during
        execution. Extra steps with execution-dependent predicates will
        always appear in dry_run output.
        """
        result: list[str] = []
        for step in self._steps:
            if step.skip_if and step.skip_if(ctx):
                continue
            result.append(step.name)
        return result


def initialize_sandbox(
    *,
    extra_steps: list[InitializeStep] | None = None,
) -> InitializeSandbox:
    """Build the standard sandbox initialization sequence.

    The default sequence is:
    1. create_sandbox — provision the sandbox via provider
    2. check_tools — diagnostic: which tools are pre-installed
    3. create_workspace_root — mkdir the workspace root directory
    4. inject_env — apply env vars (already passed to provider.create; no-op log)
    5. inject_workspace — git clone when a workspace source is present
    6. attach_mount — mount filesystem when a mount source is present
    7. run_setup_script — optional user-provided setup command

    Does **not** write harness/agent config files (settings.json, hooks).
    Those belong on a future configure endpoint.

    Extra steps are appended after the standard ones.
    """
    steps: list[InitializeStep] = [
        InitializeStep(name="create_sandbox", execute=_step_create_sandbox),
        InitializeStep(
            name="check_tools",
            execute=_step_check_tools,
            skip_if=_is_mock_provider,
        ),
        InitializeStep(name="create_workspace_root", execute=_step_create_workspace_root),
        InitializeStep(name="inject_env", execute=_step_inject_env),
        InitializeStep(
            name="inject_workspace",
            execute=_step_inject_workspace,
            skip_if=lambda ctx: ctx.workspace is None,
        ),
        InitializeStep(
            name="attach_mount",
            execute=_step_attach_mount,
            skip_if=lambda ctx: ctx.mount is None,
        ),
        InitializeStep(
            name="run_setup_script",
            execute=_step_run_setup_script,
            skip_if=lambda ctx: ctx.setup_script is None,
        ),
    ]

    if extra_steps:
        steps.extend(extra_steps)

    return InitializeSandbox(steps)


# ---------------------------------------------------------------------------
# Step implementations
# ---------------------------------------------------------------------------


def _is_mock_provider(ctx: InitializeContext) -> bool:
    return hasattr(ctx.provider, "_commands")


async def _step_create_sandbox(ctx: InitializeContext) -> None:
    await ctx.provider.create(
        env_vars=ctx.env_vars or {},
        timeout=ctx.timeout,
        snapshot_id=ctx.snapshot_id,
    )


async def _step_check_tools(ctx: InitializeContext) -> None:
    """Diagnostic: check which tools are pre-installed in the sandbox."""
    tools = {
        "git": "git",
        "python3": "python3",
        "node": "node",
        "npm": "npm",
        "bun": "bun",
        "gh": "gh",
        "uv": "uv",
        "tree": "tree",
        "rg": "rg",
        "fd": "fd",
    }
    installed_names: list[str] = []
    missing_names: list[str] = []

    for name, cmd in tools.items():
        result = await ctx.provider.run_command(
            f"command -v {cmd} >/dev/null 2>&1 && echo FOUND || echo MISSING"
        )
        if "FOUND" in result.stdout:
            installed_names.append(name)
        else:
            missing_names.append(name)

    _log.info("Pre-installed: %s", ", ".join(installed_names) if installed_names else "none")
    if missing_names:
        _log.info("Missing: %s", ", ".join(missing_names))


async def _step_create_workspace_root(ctx: InitializeContext) -> None:
    await ctx.provider.make_dir(ctx.harness_config.workspace_root)


async def _step_inject_env(ctx: InitializeContext) -> None:
    """Record that env vars were supplied at create time.

    Provider.create already receives ctx.env_vars. This step exists so the
    initialization sequence makes env injection an explicit, inspectable stage.
    """
    if ctx.env_vars:
        _log.info("Env vars applied at create (%d keys)", len(ctx.env_vars))


async def _step_inject_workspace(ctx: InitializeContext) -> None:
    if not ctx.workspace:
        return
    await ctx.workspace.inject(ctx.provider, ctx.harness_config.workspace_root)
    if hasattr(ctx.workspace, "clone_dir_name") and ctx.workspace.clone_dir_name:
        ctx.cwd = f"{ctx.harness_config.workspace_root}/{ctx.workspace.clone_dir_name}"


async def _step_attach_mount(ctx: InitializeContext) -> None:
    """Attach a filesystem/remote mount when configured.

    Provider-specific mount backends (e.g. GCS/Archil) land with Phase 2 storage.
    Until then, providers that implement ``attach_mount(source, mount_path)`` are
    invoked; otherwise this is a no-op with a warning.
    """
    if not ctx.mount:
        return
    attach = getattr(ctx.provider, "attach_mount", None)
    if attach is None:
        _log.warning(
            "Mount requested (%s → %s) but provider has no attach_mount; skipping",
            ctx.mount.source,
            ctx.mount.mount_path,
        )
        return
    await attach(ctx.mount.source, ctx.mount.mount_path)
    if not ctx.cwd:
        ctx.cwd = ctx.mount.mount_path


# ---------------------------------------------------------------------------
# Manifest helpers retained for a future configure endpoint
# ---------------------------------------------------------------------------


async def build_and_inject_manifest(ctx: InitializeContext) -> None:
    """Build harness manifest and write files (configure path, not create)."""
    await _step_build_manifest(ctx)
    await _step_create_directories(ctx)
    await _step_inject_files(ctx)
    await _step_set_hook_permissions(ctx)


async def _step_build_manifest(ctx: InitializeContext) -> None:
    from harnessbox.config.manifest import build_manifest

    target_dir = ctx.cwd if ctx.cwd else ctx.harness_config.workspace_root
    ctx.manifest_target_dir = target_dir

    ctx.manifest = build_manifest(
        harness_config=ctx.harness_config,
        security_policy=ctx.security_policy,
        workspace_root=target_dir,
        env_vars=ctx.env_vars if ctx.env_vars else None,
        dirs=ctx.dirs or None,
        files=ctx.files or None,
        system_prompt=ctx.system_prompt,
    )


async def _step_create_directories(ctx: InitializeContext) -> None:
    if not ctx.manifest:
        return
    for d in ctx.manifest.dirs:
        await ctx.provider.make_dir(d)


async def _step_inject_files(ctx: InitializeContext) -> None:
    if not ctx.manifest:
        return
    for path, content in ctx.manifest.files.items():
        await ctx.provider.write_file(path, content)


async def _step_set_hook_permissions(ctx: InitializeContext) -> None:
    if not ctx.manifest or not ctx.harness_config.hooks_dir:
        return
    hook_path = f"{ctx.manifest_target_dir}/{ctx.harness_config.hooks_dir}/guard_bash.py"
    if hook_path in ctx.manifest.files:
        await ctx.provider.run_command(f"chmod +x {hook_path}")


async def _step_run_setup_script(ctx: InitializeContext) -> None:
    """Run user-provided setup script."""
    if not ctx.setup_script:
        return
    cwd = ctx.cwd or ctx.manifest_target_dir or ctx.harness_config.workspace_root
    result = await ctx.provider.run_command(ctx.setup_script, cwd=cwd)
    if result.exit_code != 0:
        raise RuntimeError(f"Setup script failed (exit {result.exit_code}): {result.stderr}")


async def _step_load_project_config(ctx: InitializeContext) -> None:
    """Load .harnessbox.toml from the workspace and merge preset values.

    Retained for configure / power-user paths; not part of default initialize_sandbox().
    """
    from harnessbox.config.project import (
        ProjectConfigError,
        WorkspacePreset,
        load_project_config,
        merge_preset_into_context,
        register_custom_agents,
    )

    workspace_root = ctx.cwd if ctx.cwd else ctx.harness_config.workspace_root
    toml_path = f"{workspace_root}/.harnessbox.toml"

    try:
        toml_content = await ctx.provider.read_file(toml_path)
    except (FileNotFoundError, OSError):
        return

    try:
        project_config = load_project_config(toml_content)
    except ProjectConfigError as e:
        _log.warning("Invalid .harnessbox.toml, skipping: %s", e)
        return

    try:
        register_custom_agents(project_config)
    except ProjectConfigError as e:
        _log.warning("Failed to register custom agents: %s", e)

    workspace_root_for_merge = ctx.cwd if ctx.cwd else ctx.harness_config.workspace_root
    effective_preset_script = project_config.workspace.setup_script
    if not ctx.allow_project_setup_script:
        effective_preset_script = None

    merge_preset = WorkspacePreset(
        setup_script=effective_preset_script,
        env=project_config.workspace.env,
        files=project_config.workspace.files,
        extra_dirs=project_config.workspace.extra_dirs,
    )

    env_vars, files, dirs, setup_script = merge_preset_into_context(
        merge_preset,
        ctx_env_vars=ctx.env_vars,
        ctx_files=ctx.files,
        ctx_dirs=ctx.dirs,
        ctx_setup_script=ctx.setup_script,
        workspace_root=workspace_root_for_merge,
    )
    ctx.env_vars = env_vars
    ctx.files = files
    ctx.dirs = dirs
    ctx.setup_script = setup_script


# Backwards-compatible aliases (deprecated — remove after callers migrate)
SetupContext = InitializeContext
SetupStep = InitializeStep
SetupPipeline = InitializeSandbox
build_setup_pipeline = initialize_sandbox
