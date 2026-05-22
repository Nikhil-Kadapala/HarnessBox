"""Workspace primitives — clone git repos or mount storage into sandboxes."""

from __future__ import annotations

import logging
import shlex
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from harnessbox.providers import CommandResult, SandboxProvider

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class GitStatus:
    """Structured git status returned by native git providers."""

    branch: str
    ahead: int = 0
    behind: int = 0
    dirty: bool = False


@runtime_checkable
class Workspace(Protocol):
    """Protocol for workspace backends that inject files into sandboxes."""

    async def inject(self, provider: SandboxProvider, workspace_root: str) -> None:
        """Inject workspace files into the sandbox at the given root."""
        ...

    async def extract(self, provider: SandboxProvider, workspace_root: str) -> None:
        """Extract workspace state from the sandbox (e.g., commit and push)."""
        ...


EventCallback = Callable[..., Any]


class GitRepoConfig:
    """Clone a git repo into the sandbox workspace.

    Supports HTTPS remotes with optional token auth via git credential helper.
    On teardown (extract), this is a no-op — system snapshots preserve .git
    state so users can inspect and decide how to proceed.

    Example::

        workspace = GitRepoConfig(
            remote="https://github.com/user/repo.git",
            branch="main",
        )
    """

    def __init__(
        self,
        remote: str,
        *,
        branch: str = "main",
        base_branch: str | None = None,
        clone_depth: int | None = None,
        auth_token: str | None = None,
        clone_dir_name: str | None = None,
        on_clone_start: EventCallback | None = None,
        on_clone_complete: EventCallback | None = None,
    ) -> None:
        if not remote:
            raise ValueError("remote URL must not be empty")
        self.remote = remote
        self.branch = branch
        self.base_branch = base_branch or branch
        self.clone_depth = clone_depth
        self.clone_dir_name = clone_dir_name
        self._auth_token = auth_token
        self._on_clone_start = on_clone_start
        self._on_clone_complete = on_clone_complete
        self._initial_sha: str | None = None
        self.push_error: str | None = None

    def __repr__(self) -> str:
        return (
            f"GitRepoConfig(remote={self.remote!r}, branch={self.branch!r}, "
            f"clone_dir_name={self.clone_dir_name!r}, "
            f"auth_token={'***' if self._auth_token else 'None'})"
        )

    def _fire_event(self, callback: EventCallback | None, **kwargs: Any) -> None:
        if callback is not None:
            callback(**kwargs)

    async def _run_git(
        self,
        provider: SandboxProvider,
        cmd: str,
        cwd: str,
    ) -> CommandResult:
        return await provider.run_command(f"git {cmd}", cwd=cwd)

    async def inject(self, provider: SandboxProvider, workspace_root: str) -> None:
        """Clone the repo into workspace_root inside the sandbox."""
        inject_start = time.time()
        self._fire_event(self._on_clone_start, remote=self.remote, branch=self.branch)

        clone_target = (
            f"{workspace_root}/{self.clone_dir_name}" if self.clone_dir_name else workspace_root
        )

        if self.clone_dir_name:
            result = await provider.run_command(f"mkdir -p {clone_target}")
            if result.exit_code != 0:
                raise RuntimeError(f"Failed to create clone directory: {result.stderr}")

        try:
            await self._native_clone(provider, clone_target)
            _log.info(f"git_inject_total took {time.time() - inject_start:.2f}s")
            self._fire_event(
                self._on_clone_complete,
                remote=self.remote,
                branch=self.branch,
                success=True,
            )
        except Exception as e:
            self._fire_event(
                self._on_clone_complete,
                remote=self.remote,
                branch=self.branch,
                success=False,
                error=str(e),
            )
            raise RuntimeError(f"git clone failed: {e}") from e

    async def _native_clone(self, provider: Any, workspace_root: str) -> None:
        """Clone using provider's native git API."""
        await provider.git_clone(
            self.remote,
            workspace_root,
            branch=self.base_branch,
            depth=self.clone_depth,
            username="x-access-token" if self._auth_token else None,
            password=self._auth_token,
        )
        await provider.git_configure_user("harnessbox", "harnessbox@noreply", path=workspace_root)
        await provider.git_set_config("safe.directory", workspace_root, scope="global")

        if self._auth_token:
            await provider.git_dangerously_authenticate(
                username="x-access-token", password=self._auth_token
            )

        if self.branch != self.base_branch:
            await provider.git_create_branch(workspace_root, self.branch)

        sha_result = await self._run_git(provider, "rev-parse HEAD", cwd=workspace_root)
        if sha_result.exit_code == 0:
            self._initial_sha = sha_result.stdout.strip()

    async def extract(self, provider: SandboxProvider, workspace_root: str) -> None:
        """No-op — system snapshots preserve .git state for user inspection."""

    async def create_pr(
        self,
        provider: SandboxProvider,
        workspace_root: str,
        title: str,
        body: str = "",
    ) -> dict[str, str]:
        """Push the current branch and create a GitHub PR via gh CLI. Returns {"url": "..."}."""
        clone_target = self._clone_target(workspace_root)

        # Push existing commits
        push_result = await self._run_git(provider, f"push origin {self.branch}", cwd=clone_target)
        if push_result.exit_code != 0:
            self.push_error = push_result.stderr
            raise RuntimeError(f"Push failed, cannot create PR: {push_result.stderr}")

        # Set GH_TOKEN for gh CLI authentication
        env_cmd = ""
        if self._auth_token:
            env_cmd = f"GH_TOKEN={shlex.quote(self._auth_token)} "

        safe_title = shlex.quote(title)
        safe_body = shlex.quote(body)
        safe_base = shlex.quote(self.base_branch)
        safe_head = shlex.quote(self.branch)

        result = await provider.run_command(
            f"{env_cmd}gh pr create --title {safe_title} --body {safe_body} "
            f"--base {safe_base} --head {safe_head}",
            cwd=clone_target,
        )
        if result.exit_code != 0:
            raise RuntimeError(f"PR creation failed: {result.stderr}")

        pr_url = result.stdout.strip()
        return {"url": pr_url}

    async def check_pr_status(
        self,
        provider: SandboxProvider,
        workspace_root: str,
    ) -> dict[str, Any]:
        """Check PR status via gh CLI. Returns {state, merged, ci_status, url, number}."""
        clone_target = self._clone_target(workspace_root)

        env_cmd = ""
        if self._auth_token:
            env_cmd = f"GH_TOKEN={shlex.quote(self._auth_token)} "

        safe_branch = shlex.quote(self.branch)
        result = await provider.run_command(
            f"{env_cmd}gh pr view {safe_branch} --json state,merged,url,number,statusCheckRollup",
            cwd=clone_target,
        )
        if result.exit_code != 0:
            return {}

        import json

        try:
            data = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError):
            return {}

        checks = data.get("statusCheckRollup", [])
        ci_status = None
        if checks:
            conclusions = [c.get("conclusion", "").upper() for c in checks if c.get("conclusion")]
            if all(c == "SUCCESS" for c in conclusions):
                ci_status = "success"
            elif any(c == "FAILURE" for c in conclusions):
                ci_status = "failure"
            else:
                ci_status = "pending"

        return {
            "state": data.get("state", "").lower(),
            "merged": data.get("merged", False),
            "ci_status": ci_status,
            "url": data.get("url", ""),
            "number": data.get("number"),
        }

    async def rename_branch(
        self, provider: SandboxProvider, workspace_root: str, new_name: str
    ) -> None:
        """Rename the current branch in the sandbox."""
        clone_target = self._clone_target(workspace_root)
        old_name = self.branch
        result = await self._run_git(
            provider,
            f"branch -m {shlex.quote(old_name)} {shlex.quote(new_name)}",
            cwd=clone_target,
        )
        if result.exit_code != 0:
            raise RuntimeError(f"Branch rename failed: {result.stderr}")
        self.branch = new_name

    def _clone_target(self, workspace_root: str) -> str:
        return f"{workspace_root}/{self.clone_dir_name}" if self.clone_dir_name else workspace_root

    def _diff_ref(self) -> str:
        if self._initial_sha:
            return self._initial_sha
        return "HEAD"

    async def diff(self, provider: SandboxProvider, workspace_root: str) -> str:
        """Return unified diff of changes since clone (or last snapshot restore)."""
        clone_target = self._clone_target(workspace_root)
        ref = self._diff_ref()
        result = await self._run_git(provider, f"diff {ref}", cwd=clone_target)
        return result.stdout if result.exit_code == 0 else ""

    async def diff_stat(self, provider: SandboxProvider, workspace_root: str) -> dict[str, int]:
        """Return insertions/deletions since clone."""
        clone_target = self._clone_target(workspace_root)
        ref = self._diff_ref()
        result = await self._run_git(provider, f"diff --shortstat {ref}", cwd=clone_target)
        if result.exit_code != 0 or not result.stdout.strip():
            return {"insertions": 0, "deletions": 0}
        return _parse_shortstat(result.stdout)

    async def commit_count(self, provider: SandboxProvider, workspace_root: str) -> int:
        """Return number of commits since clone."""
        clone_target = self._clone_target(workspace_root)
        ref = self._diff_ref()
        result = await self._run_git(provider, f"rev-list --count {ref}..HEAD", cwd=clone_target)
        if result.exit_code != 0:
            return 0
        try:
            return int(result.stdout.strip())
        except ValueError:
            return 0


def _parse_shortstat(output: str) -> dict[str, int]:
    """Parse 'git diff --shortstat' output."""
    ins = del_ = 0
    for part in output.split(","):
        part = part.strip()
        if "insertion" in part:
            ins = int(part.split()[0])
        elif "deletion" in part:
            del_ = int(part.split()[0])
    return {"insertions": ins, "deletions": del_}
