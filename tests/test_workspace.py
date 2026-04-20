"""Tests for harnessbox.workspace — GitWorkspace, Workspace protocol."""

from __future__ import annotations

import pytest

from harnessbox.providers import CommandResult
from harnessbox.workspace import GitWorkspace, MountWorkspace, Workspace

from .conftest import MockProvider


class TestWorkspaceProtocol:
    def test_git_workspace_satisfies_protocol(self):
        ws = GitWorkspace(remote="https://github.com/test/repo.git")
        assert isinstance(ws, Workspace)


class TestGitWorkspaceInit:
    def test_basic_construction(self):
        ws = GitWorkspace(remote="https://github.com/test/repo.git")
        assert ws.remote == "https://github.com/test/repo.git"
        assert ws.branch == "main"
        assert ws.commit_on_exit is False

    def test_empty_remote_raises(self):
        with pytest.raises(ValueError, match="remote URL must not be empty"):
            GitWorkspace(remote="")

    def test_custom_params(self):
        ws = GitWorkspace(
            remote="https://github.com/test/repo.git",
            branch="dev",
            commit_on_exit=True,
            commit_message="custom msg",
            clone_depth=1,
            auth_token="ghp_test",
        )
        assert ws.branch == "dev"
        assert ws.commit_on_exit is True
        assert ws.commit_message == "custom msg"
        assert ws.clone_depth == 1

    def test_repr_redacts_token(self):
        ws = GitWorkspace(
            remote="https://github.com/test/repo.git",
            auth_token="ghp_secret123",
        )
        r = repr(ws)
        assert "ghp_secret123" not in r
        assert "***" in r

    def test_repr_shows_none_when_no_token(self):
        ws = GitWorkspace(remote="https://github.com/test/repo.git")
        r = repr(ws)
        assert "auth_token=None" in r


class _GitMockProvider(MockProvider):
    """MockProvider that simulates git command responses."""

    def __init__(self) -> None:
        super().__init__()
        self._git_responses: dict[str, CommandResult] = {}
        self._default_result = CommandResult(exit_code=0, stdout="", stderr="")

    def set_git_response(self, cmd_fragment: str, result: CommandResult) -> None:
        self._git_responses[cmd_fragment] = result

    async def run_command(self, command, cwd=None, timeout=None):
        self._commands.append(command)
        for fragment, result in self._git_responses.items():
            if fragment in command:
                return result
        return self._default_result


@pytest.fixture
def git_provider():
    return _GitMockProvider()


class TestGitWorkspaceInject:
    @pytest.mark.asyncio
    async def test_clone_public_repo(self, git_provider):
        ws = GitWorkspace(remote="https://github.com/test/repo.git")
        await ws.inject(git_provider, "/workspace")

        cmds = git_provider._commands
        assert any("git init" in c for c in cmds)
        assert any("git remote add origin" in c for c in cmds)
        assert any("git fetch origin main" in c for c in cmds)
        assert any("git checkout" in c for c in cmds)

    @pytest.mark.asyncio
    async def test_clone_with_auth_token(self, git_provider):
        ws = GitWorkspace(
            remote="https://github.com/test/repo.git",
            auth_token="ghp_test",
        )
        await ws.inject(git_provider, "/workspace")

        cmds = git_provider._commands
        remote_add = [c for c in cmds if "remote add" in c]
        assert len(remote_add) == 1
        assert "x-access-token:ghp_test@" in remote_add[0]

        set_url = [c for c in cmds if "remote set-url" in c]
        assert len(set_url) == 1
        assert "ghp_test" not in set_url[0]

        cred_cmds = [c for c in cmds if "credential.helper" in c]
        assert len(cred_cmds) == 1
        assert "ghp_test" in cred_cmds[0]

    @pytest.mark.asyncio
    async def test_clone_with_depth(self, git_provider):
        ws = GitWorkspace(
            remote="https://github.com/test/repo.git",
            clone_depth=1,
        )
        await ws.inject(git_provider, "/workspace")

        cmds = git_provider._commands
        fetch_cmd = [c for c in cmds if "fetch" in c]
        assert any("--depth 1" in c for c in fetch_cmd)

    @pytest.mark.asyncio
    async def test_clone_custom_branch(self, git_provider):
        ws = GitWorkspace(
            remote="https://github.com/test/repo.git",
            branch="develop",
        )
        await ws.inject(git_provider, "/workspace")

        cmds = git_provider._commands
        assert any("fetch origin develop" in c for c in cmds)
        assert any("origin/develop" in c for c in cmds)

    @pytest.mark.asyncio
    async def test_clone_sets_git_identity(self, git_provider):
        ws = GitWorkspace(remote="https://github.com/test/repo.git")
        await ws.inject(git_provider, "/workspace")

        cmds = git_provider._commands
        assert any("config user.name harnessbox" in c for c in cmds)
        assert any("config user.email harnessbox@noreply" in c for c in cmds)

    @pytest.mark.asyncio
    async def test_clone_sets_safe_directory(self, git_provider):
        ws = GitWorkspace(remote="https://github.com/test/repo.git")
        await ws.inject(git_provider, "/workspace")

        cmds = git_provider._commands
        assert any("safe.directory /workspace" in c for c in cmds)

    @pytest.mark.asyncio
    async def test_clone_failure_retries_on_network(self, git_provider):
        call_count = 0

        async def counting_run(command, cwd=None, timeout=None):
            nonlocal call_count
            git_provider._commands.append(command)
            if "fetch" in command:
                call_count += 1
                if call_count == 1:
                    return CommandResult(exit_code=128, stdout="", stderr="Connection timed out")
                return CommandResult(exit_code=0, stdout="", stderr="")
            return CommandResult(exit_code=0, stdout="", stderr="")

        git_provider.run_command = counting_run

        ws = GitWorkspace(remote="https://github.com/test/repo.git")
        await ws.inject(git_provider, "/workspace")
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_clone_failure_no_retry_on_auth(self, git_provider):
        git_provider.set_git_response(
            "fetch",
            CommandResult(exit_code=128, stdout="", stderr="Authentication failed"),
        )

        ws = GitWorkspace(remote="https://github.com/test/repo.git")
        with pytest.raises(RuntimeError, match="git clone failed"):
            await ws.inject(git_provider, "/workspace")

    @pytest.mark.asyncio
    async def test_clone_records_initial_sha(self, git_provider):
        git_provider.set_git_response(
            "rev-parse HEAD",
            CommandResult(exit_code=0, stdout="abc123def", stderr=""),
        )

        ws = GitWorkspace(remote="https://github.com/test/repo.git")
        await ws.inject(git_provider, "/workspace")
        assert ws._initial_sha == "abc123def"


class TestGitWorkspaceExtract:
    @pytest.mark.asyncio
    async def test_noop_when_commit_on_exit_false(self, git_provider):
        ws = GitWorkspace(
            remote="https://github.com/test/repo.git",
            commit_on_exit=False,
        )
        await ws.extract(git_provider, "/workspace")
        assert len(git_provider._commands) == 0

    @pytest.mark.asyncio
    async def test_noop_when_clean_worktree(self, git_provider):
        git_provider.set_git_response(
            "status --porcelain",
            CommandResult(exit_code=0, stdout="", stderr=""),
        )

        ws = GitWorkspace(
            remote="https://github.com/test/repo.git",
            commit_on_exit=True,
        )
        await ws.extract(git_provider, "/workspace")
        assert not any("commit" in c for c in git_provider._commands)

    @pytest.mark.asyncio
    async def test_commit_and_push_on_dirty(self, git_provider):
        git_provider.set_git_response(
            "status --porcelain",
            CommandResult(exit_code=0, stdout=" M file.txt\n", stderr=""),
        )

        ws = GitWorkspace(
            remote="https://github.com/test/repo.git",
            commit_on_exit=True,
        )
        await ws.extract(git_provider, "/workspace")

        cmds = git_provider._commands
        assert any("add -A" in c for c in cmds)
        assert any("commit" in c for c in cmds)
        assert any("push origin main" in c for c in cmds)

    @pytest.mark.asyncio
    async def test_custom_commit_message(self, git_provider):
        git_provider.set_git_response(
            "status --porcelain",
            CommandResult(exit_code=0, stdout=" M file.txt\n", stderr=""),
        )

        ws = GitWorkspace(
            remote="https://github.com/test/repo.git",
            commit_on_exit=True,
            commit_message="my custom message",
        )
        await ws.extract(git_provider, "/workspace")

        cmds = git_provider._commands
        commit_cmds = [c for c in cmds if "commit" in c]
        assert any("my custom message" in c for c in commit_cmds)

    @pytest.mark.asyncio
    async def test_default_commit_message_has_timestamp(self, git_provider):
        git_provider.set_git_response(
            "status --porcelain",
            CommandResult(exit_code=0, stdout=" M file.txt\n", stderr=""),
        )

        ws = GitWorkspace(
            remote="https://github.com/test/repo.git",
            commit_on_exit=True,
        )
        await ws.extract(git_provider, "/workspace")

        cmds = git_provider._commands
        commit_cmds = [c for c in cmds if "commit" in c]
        assert any("harnessbox: auto-commit" in c for c in commit_cmds)

    @pytest.mark.asyncio
    async def test_push_failure_sets_error(self, git_provider):
        git_provider.set_git_response(
            "status --porcelain",
            CommandResult(exit_code=0, stdout=" M file.txt\n", stderr=""),
        )
        git_provider.set_git_response(
            "push",
            CommandResult(exit_code=1, stdout="", stderr="rejected: non-fast-forward"),
        )

        ws = GitWorkspace(
            remote="https://github.com/test/repo.git",
            commit_on_exit=True,
        )
        await ws.extract(git_provider, "/workspace")
        assert ws.push_error is not None
        assert "rejected" in ws.push_error

    @pytest.mark.asyncio
    async def test_auth_token_reinjected_for_push(self, git_provider):
        git_provider.set_git_response(
            "status --porcelain",
            CommandResult(exit_code=0, stdout=" M file.txt\n", stderr=""),
        )

        ws = GitWorkspace(
            remote="https://github.com/test/repo.git",
            commit_on_exit=True,
            auth_token="ghp_push_token",
        )
        await ws.extract(git_provider, "/workspace")

        cmds = git_provider._commands
        cred_cmds = [c for c in cmds if "credential.helper" in c and "ghp_push_token" in c]
        assert len(cred_cmds) >= 1


class TestGitWorkspaceEvents:
    @pytest.mark.asyncio
    async def test_clone_events_fire(self, git_provider):
        events = []
        ws = GitWorkspace(
            remote="https://github.com/test/repo.git",
            on_clone_start=lambda **kw: events.append(("start", kw)),
            on_clone_complete=lambda **kw: events.append(("complete", kw)),
        )
        await ws.inject(git_provider, "/workspace")

        assert len(events) == 2
        assert events[0][0] == "start"
        assert events[1][0] == "complete"
        assert events[1][1]["success"] is True

    @pytest.mark.asyncio
    async def test_push_success_event(self, git_provider):
        events = []
        git_provider.set_git_response(
            "status --porcelain",
            CommandResult(exit_code=0, stdout=" M file.txt\n", stderr=""),
        )

        ws = GitWorkspace(
            remote="https://github.com/test/repo.git",
            commit_on_exit=True,
            on_push_success=lambda **kw: events.append(("push_ok", kw)),
        )
        await ws.extract(git_provider, "/workspace")

        assert len(events) == 1
        assert events[0][0] == "push_ok"

    @pytest.mark.asyncio
    async def test_push_failure_event(self, git_provider):
        events = []
        git_provider.set_git_response(
            "status --porcelain",
            CommandResult(exit_code=0, stdout=" M file.txt\n", stderr=""),
        )
        git_provider.set_git_response(
            "push",
            CommandResult(exit_code=1, stdout="", stderr="rejected"),
        )

        ws = GitWorkspace(
            remote="https://github.com/test/repo.git",
            commit_on_exit=True,
            on_push_failure=lambda **kw: events.append(("push_fail", kw)),
        )
        await ws.extract(git_provider, "/workspace")

        assert len(events) == 1
        assert events[0][0] == "push_fail"


class TestGitWorkspaceSnapshot:
    @pytest.mark.asyncio
    async def test_snapshot_creates_tag(self, git_provider):
        ws = GitWorkspace(remote="https://github.com/test/repo.git")
        await ws.snapshot(git_provider, "/workspace", "v1")

        cmds = git_provider._commands
        assert any("tag harnessbox-snap-v1" in c for c in cmds)

    @pytest.mark.asyncio
    async def test_snapshot_commits_first(self, git_provider):
        ws = GitWorkspace(remote="https://github.com/test/repo.git")
        await ws.snapshot(git_provider, "/workspace", "checkpoint")

        cmds = git_provider._commands
        add_idx = next(i for i, c in enumerate(cmds) if "add -A" in c)
        commit_idx = next(i for i, c in enumerate(cmds) if "commit" in c)
        tag_idx = next(i for i, c in enumerate(cmds) if "tag" in c)
        assert add_idx < commit_idx < tag_idx

    @pytest.mark.asyncio
    async def test_restore_checks_out_tag(self, git_provider):
        ws = GitWorkspace(remote="https://github.com/test/repo.git")
        await ws.restore(git_provider, "/workspace", "v1")

        cmds = git_provider._commands
        assert any("checkout harnessbox-snap-v1 -- ." in c for c in cmds)

    @pytest.mark.asyncio
    async def test_restore_failure_raises(self, git_provider):
        git_provider.set_git_response(
            "checkout harnessbox-snap",
            CommandResult(exit_code=1, stdout="", stderr="error: pathspec"),
        )

        ws = GitWorkspace(remote="https://github.com/test/repo.git")
        with pytest.raises(RuntimeError, match="Failed to restore snapshot"):
            await ws.restore(git_provider, "/workspace", "nonexistent")


class TestGitWorkspaceDiff:
    @pytest.mark.asyncio
    async def test_diff_against_initial_sha(self, git_provider):
        git_provider.set_git_response(
            "rev-parse HEAD",
            CommandResult(exit_code=0, stdout="abc123", stderr=""),
        )

        ws = GitWorkspace(remote="https://github.com/test/repo.git")
        await ws.inject(git_provider, "/workspace")

        git_provider.set_git_response(
            "diff abc123",
            CommandResult(exit_code=0, stdout="--- a/file.txt\n+++ b/file.txt\n", stderr=""),
        )

        result = await ws.diff(git_provider, "/workspace")
        assert "file.txt" in result

    @pytest.mark.asyncio
    async def test_diff_against_snapshot(self, git_provider):
        ws = GitWorkspace(remote="https://github.com/test/repo.git")
        ws._last_snapshot = "v1"

        git_provider.set_git_response(
            "diff harnessbox-snap-v1",
            CommandResult(exit_code=0, stdout="changes since v1", stderr=""),
        )

        result = await ws.diff(git_provider, "/workspace")
        assert "changes since v1" in result


class TestMountWorkspace:
    def test_raises_not_implemented(self):
        with pytest.raises(NotImplementedError, match="not yet implemented"):
            MountWorkspace(source="s3://bucket")
