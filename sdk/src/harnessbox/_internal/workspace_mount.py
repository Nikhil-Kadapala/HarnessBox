"""WorkspaceMount — file resolution (setup-time) and git facade (runtime)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from harnessbox.config.harness import HarnessTypeConfig
from harnessbox.config.pipeline import SetupContext
from harnessbox.providers import SandboxProvider
from harnessbox.security.policy import SecurityPolicy
from harnessbox.workspace import Workspace

if TYPE_CHECKING:
    from harnessbox.workspace import GitRepoConfig


class WorkspaceMount:
    """Combines setup-time file resolution with runtime git operations.

    Setup-time: resolves local files/skills/plugins/prompt into sandbox paths.
    Runtime: delegates git operations to the underlying GitRepoConfig workspace.
    """

    def __init__(
        self,
        harness_config: HarnessTypeConfig,
        workspace: Workspace | None,
        *,
        system_prompt: str | Path | None = None,
        skills: list[str | Path] | None = None,
        plugins: list[str | Path] | None = None,
        files: dict[str, str | Path] | list[str | Path] | None = None,
        env_vars: dict[str, str] | None = None,
        dirs: list[str] | None = None,
        setup_script: str | None = None,
        cwd: str | None = None,
    ) -> None:
        self._harness_config = harness_config
        self._workspace = workspace
        self._system_prompt_content = self._resolve_prompt(system_prompt)
        self._skills = skills or []
        self._plugins = plugins or []
        self._files = self._resolve_files(files, harness_config.workspace_root)
        self._env_vars = dict(env_vars) if env_vars else {}
        self._dirs = list(dirs) if dirs else []
        self._setup_script = setup_script
        self._cwd = cwd or harness_config.workspace_root
        self._plugin_dirs: list[str] = []

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def cwd(self) -> str:
        return self._cwd

    @cwd.setter
    def cwd(self, value: str) -> None:
        self._cwd = value

    @property
    def plugin_dirs(self) -> list[str]:
        return self._plugin_dirs

    @plugin_dirs.setter
    def plugin_dirs(self, value: list[str]) -> None:
        self._plugin_dirs = value

    @property
    def workspace(self) -> Workspace | None:
        return self._workspace

    # ------------------------------------------------------------------
    # File resolvers (pure, setup-time)
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_files(
        files: dict[str, str | Path] | list[str | Path] | None,
        workspace_root: str,
    ) -> dict[str, str]:
        if files is None:
            return {}

        resolved: dict[str, str] = {}

        if isinstance(files, list):
            for entry in files:
                p = Path(entry)
                if not p.is_file():
                    raise FileNotFoundError(
                        f"Cannot inject {p}: file not found. "
                        f"Pass a dict with raw content if the file doesn't exist on disk."
                    )
                sandbox_path = f"{workspace_root}/{p.name}"
                resolved[sandbox_path] = p.read_text(encoding="utf-8")
            return resolved

        for sandbox_path, value in files.items():
            if isinstance(value, Path):
                if not value.is_file():
                    raise FileNotFoundError(
                        f"Cannot inject {value}: file not found. "
                        f"Pass a str value for dynamically generated content."
                    )
                resolved[sandbox_path] = value.read_text(encoding="utf-8")
            else:
                resolved[sandbox_path] = value

        return resolved

    @staticmethod
    def _resolve_prompt(prompt: str | Path | None) -> str | None:
        if prompt is None:
            return None
        if isinstance(prompt, Path):
            if not prompt.is_file():
                raise FileNotFoundError(f"System prompt not found: {prompt}")
            return prompt.read_text(encoding="utf-8")
        return prompt

    def _resolve_skills(self) -> dict[str, str] | None:
        if not self._skills:
            return None
        if not self._harness_config.skills_dir:
            return None
        resolved: dict[str, str] = {}
        skills_base = f"{self._harness_config.workspace_root}/{self._harness_config.skills_dir}"
        for entry in self._skills:
            p = Path(entry)
            if p.is_dir():
                for file in p.rglob("*"):
                    if file.is_file():
                        try:
                            content = file.read_text(encoding="utf-8")
                        except UnicodeDecodeError:
                            continue
                        rel = file.relative_to(p)
                        resolved[f"{skills_base}/{p.name}/{rel}"] = content
            elif p.is_file():
                resolved[f"{skills_base}/{p.stem}/SKILL.md"] = p.read_text(encoding="utf-8")
            else:
                raise FileNotFoundError(f"Skill not found: {p}")
        return resolved

    def _resolve_plugins(self) -> tuple[dict[str, str] | None, list[str]]:
        if not self._plugins:
            return None, []
        plugin_dirs: list[str] = []
        resolved: dict[str, str] = {}
        for plugin_path in self._plugins:
            p = Path(plugin_path)
            if not p.is_dir():
                raise FileNotFoundError(f"Plugin directory not found: {p}")
            plugin_sandbox_dir = (
                f"{self._harness_config.workspace_root}/.harnessbox/plugins/{p.name}"
            )
            plugin_dirs.append(plugin_sandbox_dir)
            for file in p.rglob("*"):
                if file.is_file():
                    try:
                        content = file.read_text(encoding="utf-8")
                    except UnicodeDecodeError:
                        continue
                    rel = file.relative_to(p)
                    resolved[f"{plugin_sandbox_dir}/{rel}"] = content
        return resolved, plugin_dirs

    # ------------------------------------------------------------------
    # Setup context building
    # ------------------------------------------------------------------

    def build_setup_context(
        self,
        provider: SandboxProvider,
        security_policy: SecurityPolicy | None,
        timeout: int,
    ) -> SetupContext:
        resolved_skills = self._resolve_skills()
        resolved_plugins, plugin_dirs = self._resolve_plugins()

        return SetupContext(
            provider=provider,
            harness_config=self._harness_config,
            security_policy=security_policy,
            workspace=self._workspace,
            env_vars=self._env_vars,
            timeout=timeout,
            dirs=self._dirs,
            files=self._files,
            system_prompt=self._system_prompt_content,
            resolved_skills=resolved_skills,
            resolved_plugins=resolved_plugins,
            plugin_dirs=plugin_dirs,
            setup_script=self._setup_script,
            cwd=self._cwd,
        )

    def sync_from_setup_context(self, ctx: SetupContext) -> None:
        """Sync back state that setup pipeline may have changed."""
        if ctx.cwd:
            self._cwd = ctx.cwd
        if ctx.plugin_dirs:
            self._plugin_dirs = ctx.plugin_dirs

    # ------------------------------------------------------------------
    # Git facade (runtime)
    # ------------------------------------------------------------------

    def _git_workspace(self) -> GitRepoConfig:
        from harnessbox.workspace import GitRepoConfig

        if not self._workspace or not isinstance(self._workspace, GitRepoConfig):
            raise RuntimeError("No git workspace configured for this sandbox")
        return self._workspace

    async def rename_branch(self, provider: SandboxProvider, new_name: str) -> None:
        ws = self._git_workspace()
        await ws.rename_branch(provider, self._harness_config.workspace_root, new_name)

    async def create_pr(
        self, provider: SandboxProvider, title: str, body: str = ""
    ) -> dict[str, str]:
        ws = self._git_workspace()
        return await ws.create_pr(provider, self._harness_config.workspace_root, title, body)

    async def check_pr_status(self, provider: SandboxProvider) -> dict[str, Any]:
        ws = self._git_workspace()
        return await ws.check_pr_status(provider, self._harness_config.workspace_root)

    async def diff(self, provider: SandboxProvider) -> str:
        ws = self._git_workspace()
        return await ws.diff(provider, self._harness_config.workspace_root)

    async def diff_stat(self, provider: SandboxProvider) -> dict[str, int]:
        ws = self._git_workspace()
        return await ws.diff_stat(provider, self._harness_config.workspace_root)

    async def commit_count(self, provider: SandboxProvider) -> int:
        ws = self._git_workspace()
        return await ws.commit_count(provider, self._harness_config.workspace_root)

    async def create_checkpoint(self, provider: SandboxProvider, name: str) -> None:
        ws = self._git_workspace()
        await ws.create_checkpoint(provider, self._harness_config.workspace_root, name)

    async def restore_checkpoint(self, provider: SandboxProvider, name: str) -> None:
        ws = self._git_workspace()
        await ws.restore_checkpoint(provider, self._harness_config.workspace_root, name)
