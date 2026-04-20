"""Workspace primitives — clone git repos or mount storage into sandboxes."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

from harnessbox.providers import CommandResult, SandboxProvider


@runtime_checkable
class Workspace(Protocol):
    """Protocol for workspace backends that inject files into sandboxes."""

    async def inject(self, provider: SandboxProvider, workspace_root: str) -> None: ...

    async def extract(self, provider: SandboxProvider, workspace_root: str) -> None: ...


EventCallback = Callable[..., Any]


class GitWorkspace:
    """Clone a git repo into the sandbox workspace.

    Supports HTTPS remotes with optional token auth via git credential helper.
    Optionally commits and pushes on extract (teardown).

    Example::

        workspace = GitWorkspace(
            remote="https://github.com/user/repo.git",
            branch="main",
            commit_on_exit=True,
        )
    """

    def __init__(
        self,
        remote: str,
        *,
        branch: str = "main",
        commit_on_exit: bool = False,
        commit_message: str | None = None,
        clone_depth: int | None = None,
        auth_token: str | None = None,
        on_clone_start: EventCallback | None = None,
        on_clone_complete: EventCallback | None = None,
        on_commit: EventCallback | None = None,
        on_push_success: EventCallback | None = None,
        on_push_failure: EventCallback | None = None,
    ) -> None:
        if not remote:
            raise ValueError("remote URL must not be empty")
        self.remote = remote
        self.branch = branch
        self.commit_on_exit = commit_on_exit
        self.commit_message = commit_message
        self.clone_depth = clone_depth
        self._auth_token = auth_token
        self._on_clone_start = on_clone_start
        self._on_clone_complete = on_clone_complete
        self._on_commit = on_commit
        self._on_push_success = on_push_success
        self._on_push_failure = on_push_failure
        self._initial_sha: str | None = None
        self._last_snapshot: str | None = None
        self.push_error: str | None = None

    def __repr__(self) -> str:
        return (
            f"GitWorkspace(remote={self.remote!r}, branch={self.branch!r}, "
            f"commit_on_exit={self.commit_on_exit}, "
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

    def _authed_remote(self) -> str:
        if self._auth_token and self.remote.startswith("https://"):
            return self.remote.replace("https://", f"https://x-access-token:{self._auth_token}@")
        return self.remote

    def _clean_remote(self) -> str:
        return self.remote

    async def inject(self, provider: SandboxProvider, workspace_root: str) -> None:
        """Clone the repo into workspace_root inside the sandbox."""
        self._fire_event(self._on_clone_start, remote=self.remote, branch=self.branch)

        for attempt in range(2):
            try:
                await self._do_clone(provider, workspace_root)
                self._fire_event(
                    self._on_clone_complete,
                    remote=self.remote,
                    branch=self.branch,
                    success=True,
                )
                return
            except _CloneError as e:
                if e.retryable and attempt == 0:
                    continue
                self._fire_event(
                    self._on_clone_complete,
                    remote=self.remote,
                    branch=self.branch,
                    success=False,
                    error=str(e),
                )
                raise RuntimeError(f"git clone failed: {e}") from e

    async def _do_clone(self, provider: SandboxProvider, workspace_root: str) -> None:
        result = await self._run_git(provider, "init", cwd=workspace_root)
        if result.exit_code != 0:
            raise _CloneError(f"git init failed: {result.stderr}", retryable=False)

        await self._run_git(
            provider,
            f"remote add origin {self._authed_remote()}",
            cwd=workspace_root,
        )

        await self._run_git(
            provider,
            "config user.name harnessbox",
            cwd=workspace_root,
        )
        await self._run_git(
            provider,
            "config user.email harnessbox@noreply",
            cwd=workspace_root,
        )
        await self._run_git(
            provider,
            f"config --global safe.directory {workspace_root}",
            cwd=workspace_root,
        )

        depth_flag = f"--depth {self.clone_depth}" if self.clone_depth else ""
        result = await self._run_git(
            provider,
            f"fetch origin {self.branch} {depth_flag}".strip(),
            cwd=workspace_root,
        )
        if result.exit_code != 0:
            retryable = not self._is_auth_or_notfound(result.stderr)
            raise _CloneError(f"git fetch failed: {result.stderr}", retryable=retryable)

        result = await self._run_git(
            provider,
            f"checkout -b {self.branch} origin/{self.branch}",
            cwd=workspace_root,
        )
        if result.exit_code != 0:
            raise _CloneError(f"git checkout failed: {result.stderr}", retryable=False)

        await self._run_git(
            provider,
            f"remote set-url origin {self._clean_remote()}",
            cwd=workspace_root,
        )

        if self._auth_token:
            helper_cmd = f"!echo password={self._auth_token}"
            await self._run_git(
                provider,
                f"config credential.helper '{helper_cmd}'",
                cwd=workspace_root,
            )

        sha_result = await self._run_git(provider, "rev-parse HEAD", cwd=workspace_root)
        if sha_result.exit_code == 0:
            self._initial_sha = sha_result.stdout.strip()

        lfs_result = await self._run_git(provider, "lfs ls-files 2>/dev/null", cwd=workspace_root)
        if lfs_result.exit_code == 0 and lfs_result.stdout.strip():
            pass

        sub_result = await provider.run_command(
            f"test -f {workspace_root}/.gitmodules && echo HAS_SUBMODULES || echo NONE",
            cwd=workspace_root,
        )
        if "HAS_SUBMODULES" in sub_result.stdout:
            pass

    @staticmethod
    def _is_auth_or_notfound(stderr: str) -> bool:
        indicators = ["401", "403", "404", "Authentication failed", "not found", "does not exist"]
        return any(ind.lower() in stderr.lower() for ind in indicators)

    async def extract(self, provider: SandboxProvider, workspace_root: str) -> None:
        """If commit_on_exit, commit and push. Otherwise no-op."""
        if not self.commit_on_exit:
            return

        result = await self._run_git(provider, "status --porcelain", cwd=workspace_root)
        if result.exit_code != 0 or not result.stdout.strip():
            return

        await self._run_git(provider, "add -A", cwd=workspace_root)

        msg = (
            self.commit_message
            or f"harnessbox: auto-commit {datetime.now(timezone.utc).isoformat()}"
        )
        commit_result = await self._run_git(provider, f'commit -m "{msg}"', cwd=workspace_root)
        if commit_result.exit_code == 0:
            sha = commit_result.stdout.strip().split()[-1] if commit_result.stdout else ""
            self._fire_event(self._on_commit, sha=sha, message=msg)

        if self._auth_token:
            helper_cmd = f"!echo password={self._auth_token}"
            await self._run_git(
                provider,
                f"config credential.helper '{helper_cmd}'",
                cwd=workspace_root,
            )

        push_result = await self._run_git(
            provider, f"push origin {self.branch}", cwd=workspace_root
        )
        if push_result.exit_code != 0:
            self.push_error = push_result.stderr
            self._fire_event(self._on_push_failure, error=push_result.stderr, branch=self.branch)
        else:
            self._fire_event(self._on_push_success, branch=self.branch)
            if self._auth_token:
                await self._run_git(
                    provider, "config --unset credential.helper", cwd=workspace_root
                )

    async def snapshot(self, provider: SandboxProvider, workspace_root: str, name: str) -> None:
        """Create a named snapshot (lightweight git tag) at the current state."""
        await self._run_git(provider, "add -A", cwd=workspace_root)
        await self._run_git(
            provider,
            f'commit --allow-empty -m "snapshot: {name}"',
            cwd=workspace_root,
        )
        tag_result = await self._run_git(
            provider, f"tag harnessbox-snap-{name}", cwd=workspace_root
        )
        if tag_result.exit_code != 0:
            raise RuntimeError(f"Failed to create snapshot {name!r}: {tag_result.stderr}")
        self._last_snapshot = name

    async def restore(self, provider: SandboxProvider, workspace_root: str, name: str) -> None:
        """Restore to a named snapshot."""
        result = await self._run_git(
            provider, f"checkout harnessbox-snap-{name} -- .", cwd=workspace_root
        )
        if result.exit_code != 0:
            raise RuntimeError(f"Failed to restore snapshot {name!r}: {result.stderr}")
        self._last_snapshot = name

    async def diff(self, provider: SandboxProvider, workspace_root: str) -> str:
        """Return unified diff of changes since clone (or last snapshot restore)."""
        if self._last_snapshot:
            ref = f"harnessbox-snap-{self._last_snapshot}"
        elif self._initial_sha:
            ref = self._initial_sha
        else:
            ref = "HEAD"
        result = await self._run_git(provider, f"diff {ref}", cwd=workspace_root)
        return result.stdout if result.exit_code == 0 else ""


class MountWorkspace:
    """Placeholder for mount-based workspace (S3, GCS, local directory)."""

    def __init__(self, source: str, *, sync_on_exit: bool = False) -> None:
        raise NotImplementedError(
            "MountWorkspace is not yet implemented. Use GitWorkspace for git repos."
        )


class _CloneError(Exception):
    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable
