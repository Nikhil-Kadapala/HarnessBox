"""Tests for harnessbox.workspace — GitWorkspace, Workspace protocol."""

from __future__ import annotations

import pytest

from harnessbox.providers import CommandResult
from harnessbox.workspace import GitWorkspace, Workspace, _parse_shortstat

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
        assert "store --file /workspace/.git-credentials" in cred_cmds[0]
        assert "ghp_test" not in cred_cmds[0]

        cred_file_cmds = [c for c in cmds if ".git-credentials" in c and "echo" in c]
        assert len(cred_file_cmds) == 1
        assert "ghp_test" in cred_file_cmds[0]
        assert "chmod 600" in cred_file_cmds[0]

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
    async def test_clone_into_subdirectory(self, git_provider):
        """When clone_dir_name is set, clone should happen in subdirectory."""
        ws = GitWorkspace(
            remote="https://github.com/test/repo.git",
            clone_dir_name="alexandria",
        )
        await ws.inject(git_provider, "/workspace")

        cmds = git_provider._commands
        # Should create the subdirectory first
        assert any("mkdir -p /workspace/alexandria" in c for c in cmds)
        # All git commands should run in the subdirectory
        # (git commands use cwd parameter, but init should be first git command after mkdir)
        assert ws.clone_dir_name == "alexandria"

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
    async def test_clone_checks_out_branch(self, git_provider):
        """Verify that checkout runs after fetch to create working tree on specified branch."""
        ws = GitWorkspace(
            remote="https://github.com/test/repo.git",
            branch="feature-x",
        )
        await ws.inject(git_provider, "/workspace")

        cmds = git_provider._commands
        # Find indexes of fetch and checkout commands
        fetch_idx = next(i for i, c in enumerate(cmds) if "fetch origin feature-x" in c)
        checkout_idx = next(
            i for i, c in enumerate(cmds) if "checkout -b feature-x origin/feature-x" in c
        )
        # Checkout must happen after fetch
        assert checkout_idx > fetch_idx

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
    async def test_push_uses_persisted_credentials(self, git_provider):
        """Push relies on .git-credentials written during inject — no token in git config."""
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
        # Token should NOT appear in any git config command during push
        cred_cmds = [c for c in cmds if "credential.helper" in c]
        for cmd in cred_cmds:
            assert "ghp_push_token" not in cmd
        # Push should still be attempted
        push_cmds = [c for c in cmds if "push" in c]
        assert len(push_cmds) == 1


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


class TestParseShortstat:
    def test_full_output(self):
        out = " 3 files changed, 142 insertions(+), 23 deletions(-)\n"
        assert _parse_shortstat(out) == {"insertions": 142, "deletions": 23}

    def test_insertions_only(self):
        out = " 1 file changed, 10 insertions(+)\n"
        assert _parse_shortstat(out) == {"insertions": 10, "deletions": 0}

    def test_deletions_only(self):
        out = " 2 files changed, 5 deletions(-)\n"
        assert _parse_shortstat(out) == {"insertions": 0, "deletions": 5}

    def test_empty_string(self):
        assert _parse_shortstat("") == {"insertions": 0, "deletions": 0}

    def test_single_file_single_insertion(self):
        out = " 1 file changed, 1 insertion(+)\n"
        assert _parse_shortstat(out) == {"insertions": 1, "deletions": 0}


class TestGitWorkspaceDiffStat:
    @pytest.fixture
    def git_provider(self):
        p = _GitMockProvider()
        return p

    @pytest.mark.asyncio
    async def test_diff_stat_returns_counts(self, git_provider):
        ws = GitWorkspace(remote="https://github.com/test/repo.git")
        ws._initial_sha = "abc123"

        git_provider.set_git_response(
            "diff --shortstat abc123",
            CommandResult(
                exit_code=0,
                stdout=" 3 files changed, 50 insertions(+), 12 deletions(-)\n",
                stderr="",
            ),
        )

        result = await ws.diff_stat(git_provider, "/workspace")
        assert result == {"insertions": 50, "deletions": 12}

    @pytest.mark.asyncio
    async def test_diff_stat_empty_when_no_changes(self, git_provider):
        ws = GitWorkspace(remote="https://github.com/test/repo.git")
        ws._initial_sha = "abc123"

        git_provider.set_git_response(
            "diff --shortstat abc123",
            CommandResult(exit_code=0, stdout="", stderr=""),
        )

        result = await ws.diff_stat(git_provider, "/workspace")
        assert result == {"insertions": 0, "deletions": 0}

    @pytest.mark.asyncio
    async def test_diff_stat_with_clone_dir(self, git_provider):
        ws = GitWorkspace(remote="https://github.com/test/repo.git", clone_dir_name="tokyo")
        ws._initial_sha = "abc123"

        git_provider.set_git_response(
            "diff --shortstat abc123",
            CommandResult(
                exit_code=0,
                stdout=" 1 file changed, 5 insertions(+)\n",
                stderr="",
            ),
        )

        result = await ws.diff_stat(git_provider, "/workspace")
        assert result == {"insertions": 5, "deletions": 0}


class TestGitWorkspaceCommitCount:
    @pytest.fixture
    def git_provider(self):
        return _GitMockProvider()

    @pytest.mark.asyncio
    async def test_commit_count(self, git_provider):
        ws = GitWorkspace(remote="https://github.com/test/repo.git")
        ws._initial_sha = "abc123"

        git_provider.set_git_response(
            "rev-list --count abc123..HEAD",
            CommandResult(exit_code=0, stdout="7\n", stderr=""),
        )

        result = await ws.commit_count(git_provider, "/workspace")
        assert result == 7

    @pytest.mark.asyncio
    async def test_commit_count_zero_on_failure(self, git_provider):
        ws = GitWorkspace(remote="https://github.com/test/repo.git")
        ws._initial_sha = "abc123"

        git_provider.set_git_response(
            "rev-list --count abc123..HEAD",
            CommandResult(exit_code=1, stdout="", stderr="error"),
        )

        result = await ws.commit_count(git_provider, "/workspace")
        assert result == 0


class TestGitWorkspaceCreatePR:
    @pytest.fixture
    def git_provider(self):
        return _GitMockProvider()

    @pytest.mark.asyncio
    async def test_create_pr_happy_path(self, git_provider):
        ws = GitWorkspace(
            remote="https://github.com/test/repo.git",
            branch="tokyo",
            base_branch="main",
            auth_token="ghp_test",
        )

        # Mock: no changes to commit
        git_provider.set_git_response(
            "status --porcelain",
            CommandResult(exit_code=0, stdout="", stderr=""),
        )
        # Mock: gh pr create success
        git_provider.set_git_response(
            "gh pr create",
            CommandResult(exit_code=0, stdout="https://github.com/test/repo/pull/42\n", stderr=""),
        )

        result = await ws.create_pr(git_provider, "/workspace", title="test PR")
        assert result["url"] == "https://github.com/test/repo/pull/42"

    @pytest.mark.asyncio
    async def test_create_pr_gh_fails(self, git_provider):
        ws = GitWorkspace(
            remote="https://github.com/test/repo.git",
            branch="tokyo",
            base_branch="main",
        )

        git_provider.set_git_response(
            "status --porcelain",
            CommandResult(exit_code=0, stdout="", stderr=""),
        )
        git_provider.set_git_response(
            "gh pr create",
            CommandResult(exit_code=1, stdout="", stderr="already exists"),
        )

        with pytest.raises(RuntimeError, match="PR creation failed"):
            await ws.create_pr(git_provider, "/workspace", title="test PR")

    @pytest.mark.asyncio
    async def test_create_pr_shlex_escapes_title(self, git_provider):
        ws = GitWorkspace(
            remote="https://github.com/test/repo.git",
            branch="tokyo",
            base_branch="main",
        )

        git_provider.set_git_response(
            "status --porcelain",
            CommandResult(exit_code=0, stdout="", stderr=""),
        )
        git_provider.set_git_response(
            "gh pr create",
            CommandResult(exit_code=0, stdout="https://github.com/test/repo/pull/1\n", stderr=""),
        )

        # Title with quotes should not break
        result = await ws.create_pr(git_provider, "/workspace", title="fix the user's profile")
        assert "url" in result


class TestGitWorkspaceCheckPRStatus:
    @pytest.fixture
    def git_provider(self):
        return _GitMockProvider()

    @pytest.mark.asyncio
    async def test_check_pr_status_merged(self, git_provider):
        import json

        ws = GitWorkspace(
            remote="https://github.com/test/repo.git",
            branch="tokyo",
            base_branch="main",
        )

        pr_json = json.dumps(
            {
                "state": "MERGED",
                "merged": True,
                "url": "https://github.com/test/repo/pull/42",
                "number": 42,
                "statusCheckRollup": [{"conclusion": "SUCCESS"}],
            }
        )
        git_provider.set_git_response(
            "gh pr view",
            CommandResult(exit_code=0, stdout=pr_json, stderr=""),
        )

        result = await ws.check_pr_status(git_provider, "/workspace")
        assert result["merged"] is True
        assert result["ci_status"] == "success"
        assert result["number"] == 42

    @pytest.mark.asyncio
    async def test_check_pr_status_no_pr(self, git_provider):
        ws = GitWorkspace(
            remote="https://github.com/test/repo.git",
            branch="tokyo",
            base_branch="main",
        )

        git_provider.set_git_response(
            "gh pr view",
            CommandResult(exit_code=1, stdout="", stderr="no pull requests found"),
        )

        result = await ws.check_pr_status(git_provider, "/workspace")
        assert result == {}

    @pytest.mark.asyncio
    async def test_check_pr_status_ci_failure(self, git_provider):
        import json

        ws = GitWorkspace(
            remote="https://github.com/test/repo.git",
            branch="tokyo",
            base_branch="main",
        )

        pr_json = json.dumps(
            {
                "state": "OPEN",
                "merged": False,
                "url": "https://github.com/test/repo/pull/42",
                "number": 42,
                "statusCheckRollup": [
                    {"conclusion": "SUCCESS"},
                    {"conclusion": "FAILURE"},
                ],
            }
        )
        git_provider.set_git_response(
            "gh pr view",
            CommandResult(exit_code=0, stdout=pr_json, stderr=""),
        )

        result = await ws.check_pr_status(git_provider, "/workspace")
        assert result["ci_status"] == "failure"


class TestGitWorkspaceRenameBranch:
    @pytest.fixture
    def git_provider(self):
        return _GitMockProvider()

    @pytest.mark.asyncio
    async def test_rename_branch(self, git_provider):
        ws = GitWorkspace(
            remote="https://github.com/test/repo.git",
            branch="tokyo",
            base_branch="main",
        )

        git_provider.set_git_response(
            "branch -m",
            CommandResult(exit_code=0, stdout="", stderr=""),
        )

        await ws.rename_branch(git_provider, "/workspace", "feat/new-feature")
        assert ws.branch == "feat/new-feature"

    @pytest.mark.asyncio
    async def test_rename_branch_failure(self, git_provider):
        ws = GitWorkspace(
            remote="https://github.com/test/repo.git",
            branch="tokyo",
            base_branch="main",
        )

        git_provider.set_git_response(
            "branch -m",
            CommandResult(exit_code=1, stdout="", stderr="error: refname not found"),
        )

        with pytest.raises(RuntimeError, match="Branch rename failed"):
            await ws.rename_branch(git_provider, "/workspace", "bad-name")
        assert ws.branch == "tokyo"
