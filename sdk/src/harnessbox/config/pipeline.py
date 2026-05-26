"""Setup pipeline — sequential step execution for sandbox provisioning."""

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
class SetupContext:
    """Mutable state carried across pipeline steps.

    Each step reads from and writes to this context. The pipeline
    guarantees steps run in declaration order, so earlier writes
    are visible to later reads.
    """

    provider: SandboxProvider
    harness_config: HarnessTypeConfig
    security_policy: SecurityPolicy | None = None
    workspace: Workspace | None = None
    env_vars: dict[str, str] = field(default_factory=dict)
    timeout: int = 300

    # User-provided inputs
    dirs: list[str] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)
    system_prompt: str | None = None
    resolved_skills: dict[str, str] | None = None
    resolved_plugins: dict[str, str] | None = None
    plugin_dirs: list[str] = field(default_factory=list)
    setup_script: str | None = None

    # Snapshot-based creation (skips template)
    snapshot_id: str | None = None

    # Populated during execution
    manifest: SandboxManifest | None = None
    manifest_target_dir: str = ""
    cwd: str = ""

    # Step timing records
    timings: dict[str, float] = field(default_factory=dict)


StepFn = Callable[[SetupContext], Awaitable[None]]


@dataclass(frozen=True)
class SetupStep:
    """A named step in the setup pipeline."""

    name: str
    execute: StepFn
    skip_if: Callable[[SetupContext], bool] | None = None


class SetupPipeline:
    """Sequential pipeline of setup steps.

    Steps execute in declaration order. Each step receives the shared
    SetupContext. If a step raises, execution halts and the exception
    propagates.

    Supports dry-run (returns step names without executing) and
    per-step timing.
    """

    def __init__(self, steps: list[SetupStep]) -> None:
        self._steps = list(steps)

    @property
    def steps(self) -> list[SetupStep]:
        """Return the ordered list of pipeline steps."""
        return list(self._steps)

    def step_names(self) -> list[str]:
        """Return ordered step names (useful for dry-run inspection)."""
        return [s.name for s in self._steps]

    async def execute(self, ctx: SetupContext) -> dict[str, float]:
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
        _log.info("setup_total took %.2fs", total)

        return ctx.timings

    def dry_run(self, ctx: SetupContext) -> list[str]:
        """Return step names that would execute (respecting skip_if).

        Note: skip_if predicates are evaluated against the initial context
        without running preceding steps. Predicates should only inspect
        fields set at construction time, not fields populated during
        execution (e.g., ctx.manifest). Extra steps with execution-dependent
        predicates will always appear in dry_run output.
        """
        result: list[str] = []
        for step in self._steps:
            if step.skip_if and step.skip_if(ctx):
                continue
            result.append(step.name)
        return result


def build_setup_pipeline(
    *,
    extra_steps: list[SetupStep] | None = None,
) -> SetupPipeline:
    """Build the standard setup pipeline.

    The default pipeline is:
    1. create_sandbox — provision the sandbox via provider
    2. check_tools — diagnostic: which tools are pre-installed
    3. create_workspace_root — mkdir the workspace root directory
    4. inject_workspace — git clone or mount filesystem
    5. load_project_config — read .harnessbox.toml and merge presets
    6. build_manifest — compute files/dirs/env to inject (pure)
    7. create_directories — mkdir all manifest directories
    8. inject_files — write all manifest files
    9. set_hook_permissions — chmod hook scripts
    10. run_setup_script — user-provided setup command

    Extra steps are appended after the standard ones.
    """
    steps: list[SetupStep] = [
        SetupStep(name="create_sandbox", execute=_step_create_sandbox),
        SetupStep(
            name="check_tools",
            execute=_step_check_tools,
            skip_if=_is_mock_provider,
        ),
        SetupStep(name="create_workspace_root", execute=_step_create_workspace_root),
        SetupStep(
            name="inject_workspace",
            execute=_step_inject_workspace,
            skip_if=lambda ctx: ctx.workspace is None,
        ),
        SetupStep(
            name="load_project_config",
            execute=_step_load_project_config,
            skip_if=_is_mock_provider,
        ),
        SetupStep(name="build_manifest", execute=_step_build_manifest),
        SetupStep(name="create_directories", execute=_step_create_directories),
        SetupStep(name="inject_files", execute=_step_inject_files),
        SetupStep(
            name="set_hook_permissions",
            execute=_step_set_hook_permissions,
            skip_if=lambda ctx: not ctx.security_policy or not ctx.harness_config.hooks_dir,
        ),
        SetupStep(
            name="run_setup_script",
            execute=_step_run_setup_script,
            skip_if=lambda ctx: ctx.setup_script is None,
        ),
    ]

    if extra_steps:
        steps.extend(extra_steps)

    return SetupPipeline(steps)


# ---------------------------------------------------------------------------
# Step implementations
# ---------------------------------------------------------------------------


def _is_mock_provider(ctx: SetupContext) -> bool:
    return hasattr(ctx.provider, "_commands")


async def _step_create_sandbox(ctx: SetupContext) -> None:
    await ctx.provider.create(
        env_vars=ctx.env_vars or {},
        timeout=ctx.timeout,
        snapshot_id=ctx.snapshot_id,
    )


async def _step_check_tools(ctx: SetupContext) -> None:
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


async def _step_create_workspace_root(ctx: SetupContext) -> None:
    await ctx.provider.make_dir(ctx.harness_config.workspace_root)


async def _step_inject_workspace(ctx: SetupContext) -> None:
    if not ctx.workspace:
        return
    await ctx.workspace.inject(ctx.provider, ctx.harness_config.workspace_root)
    if hasattr(ctx.workspace, "clone_dir_name") and ctx.workspace.clone_dir_name:
        ctx.cwd = f"{ctx.harness_config.workspace_root}/{ctx.workspace.clone_dir_name}"


async def _step_build_manifest(ctx: SetupContext) -> None:
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
        skills=ctx.resolved_skills,
        plugins=ctx.resolved_plugins,
    )


async def _step_create_directories(ctx: SetupContext) -> None:
    if not ctx.manifest:
        return
    for d in ctx.manifest.dirs:
        await ctx.provider.make_dir(d)


async def _step_inject_files(ctx: SetupContext) -> None:
    if not ctx.manifest:
        return
    for path, content in ctx.manifest.files.items():
        await ctx.provider.write_file(path, content)


async def _step_set_hook_permissions(ctx: SetupContext) -> None:
    if not ctx.manifest or not ctx.harness_config.hooks_dir:
        return
    hook_path = f"{ctx.manifest_target_dir}/{ctx.harness_config.hooks_dir}/guard_bash.py"
    if hook_path in ctx.manifest.files:
        await ctx.provider.run_command(f"chmod +x {hook_path}")


async def _step_run_setup_script(ctx: SetupContext) -> None:
    """Run user-provided setup script."""
    if not ctx.setup_script:
        return
    result = await ctx.provider.run_command(ctx.setup_script, cwd=ctx.manifest_target_dir)
    if result.exit_code != 0:
        raise RuntimeError(f"Setup script failed (exit {result.exit_code}): {result.stderr}")


async def _step_load_project_config(ctx: SetupContext) -> None:
    """Load .harnessbox.toml from the workspace and merge preset values."""
    from harnessbox.config.project import (
        ProjectConfigError,
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

    env_vars, files, dirs, setup_script = merge_preset_into_context(
        project_config.workspace,
        ctx_env_vars=ctx.env_vars,
        ctx_files=ctx.files,
        ctx_dirs=ctx.dirs,
        ctx_setup_script=ctx.setup_script,
    )
    ctx.env_vars = env_vars
    ctx.files = files
    ctx.dirs = dirs
    ctx.setup_script = setup_script
