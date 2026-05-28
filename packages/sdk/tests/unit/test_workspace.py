"""Tests for harnessbox.workspace — GitRepoConfig, Workspace protocol."""

from __future__ import annotations

import pytest

from harnessbox.providers import CommandResult
from harnessbox.workspace import GitRepoConfig, Workspace, _parse_shortstat


class TestWorkspaceProtocol:
    def test_git_repo_config_satisfies_protocol(self):
        ws = GitRepoConfig(remote="https://github.com/test/repo.git")
        assert isinstance(ws, Workspace)


class TestGitRepoConfigInit:
    def test_basic_construction(self):
        ws = GitRepoConfig(remote="https://github.com/test/repo.git")
        assert ws.remote == "https://github.com/test/repo.git"
        assert ws.branch == "main"

    def test_empty_remote_raises(self):
        with pytest.raises(ValueError, match="remote URL must not be empty"):
            GitRepoConfig(remote="")

    def test_custom_params(self):
        ws = GitRepoConfig(
            remote="https://github.com/test/repo.git",
            branch="dev",
            clone_depth=1,
            auth_token="ghp_test",
        )
        assert ws.branch == "dev"
        assert ws.clone_depth == 1

    def test_repr_redacts_token(self):
        ws = GitRepoConfig(
            remote="https://github.com/test/repo.git",
            auth_token="ghp_secret123",
        )
        r = repr(ws)
        assert "ghp_secret123" not in r
        assert "***" in r

    def test_repr_shows_none_when_no_token(self):
        ws = GitRepoConfig(remote="https://github.com/test/repo.git")
        r = repr(ws)
        assert "auth_token=None" in r


class TestGitRepoConfigInject:
    @pytest.mark.asyncio
    async def test_clone_public_repo(self, mock_provider):
        ws = GitRepoConfig(remote="https://github.com/test/repo.git")
        await ws.inject(mock_provider, "/workspace")

        cmds = mock_provider._commands
        assert any("git_clone:https://github.com/test/repo.git:/workspace" in c for c in cmds)
        assert any("git_configure_user:harnessbox:harnessbox@noreply" in c for c in cmds)
        assert any("git_set_config:safe.directory=/workspace:scope=global" in c for c in cmds)

    @pytest.mark.asyncio
    async def test_clone_with_auth_uses_dangerously_authenticate(self, mock_provider):
        ws = GitRepoConfig(
            remote="https://github.com/test/repo.git",
            auth_token="ghp_test",
        )
        await ws.inject(mock_provider, "/workspace")

        cmds = mock_provider._commands
        # Native clone should pass credentials
        clone_cmd = [c for c in cmds if "git_clone:" in c][0]
        assert "branch=main" in clone_cmd

        # Should use dangerously_authenticate instead of shell credential setup
        auth_cmds = [c for c in cmds if "git_dangerously_authenticate:" in c]
        assert len(auth_cmds) == 1
        assert "x-access-token" in auth_cmds[0]

        # Token should never appear in shell commands
        shell_cmds = [c for c in cmds if not c.startswith("git_")]
        for cmd in shell_cmds:
            assert "ghp_test" not in cmd

    @pytest.mark.asyncio
    async def test_clone_without_auth_skips_authenticate(self, mock_provider):
        ws = GitRepoConfig(remote="https://github.com/test/repo.git")
        await ws.inject(mock_provider, "/workspace")

        cmds = mock_provider._commands
        assert not any("git_dangerously_authenticate" in c for c in cmds)

    @pytest.mark.asyncio
    async def test_clone_with_depth(self, mock_provider):
        ws = GitRepoConfig(
            remote="https://github.com/test/repo.git",
            clone_depth=1,
        )
        await ws.inject(mock_provider, "/workspace")

        cmds = mock_provider._commands
        clone_cmd = [c for c in cmds if "git_clone:" in c][0]
        assert "depth=1" in clone_cmd

    @pytest.mark.asyncio
    async def test_clone_into_subdirectory(self, mock_provider):
        ws = GitRepoConfig(
            remote="https://github.com/test/repo.git",
            clone_dir_name="alexandria",
        )
        await ws.inject(mock_provider, "/workspace")

        cmds = mock_provider._commands
        assert any("mkdir -p /workspace/alexandria" in c for c in cmds)
        clone_cmd = [c for c in cmds if "git_clone:" in c][0]
        assert "/workspace/alexandria" in clone_cmd

    @pytest.mark.asyncio
    async def test_clone_feature_branch_uses_create_branch(self, mock_provider):
        async def patched_run(command, cwd=None, timeout=None):
            mock_provider._commands.append(command)
            if "rev-parse --verify origin/feat/new" in command:
                return CommandResult(exit_code=1, stdout="", stderr="")
            return CommandResult(exit_code=0, stdout="", stderr="")

        mock_provider.run_command = patched_run

        ws = GitRepoConfig(
            remote="https://github.com/test/repo.git",
            branch="feat/new",
            base_branch="main",
        )
        await ws.inject(mock_provider, "/workspace")

        cmds = mock_provider._commands
        # Clone uses base_branch
        clone_cmd = [c for c in cmds if "git_clone:" in c][0]
        assert "branch=main" in clone_cmd

        # Then creates feature branch
        branch_cmds = [c for c in cmds if "git_create_branch:" in c]
        assert len(branch_cmds) == 1
        assert "feat/new" in branch_cmds[0]

    @pytest.mark.asyncio
    async def test_clone_same_branch_skips_create_branch(self, mock_provider):
        ws = GitRepoConfig(
            remote="https://github.com/test/repo.git",
            branch="main",
            base_branch="main",
        )
        await ws.inject(mock_provider, "/workspace")

        cmds = mock_provider._commands
        assert not any("git_create_branch:" in c for c in cmds)

    @pytest.mark.asyncio
    async def test_clone_raises_when_branch_exists_remotely(self, mock_provider):
        """Default behavior: raise GitBranchAlreadyExistsError if branch exists on remote."""
        from harnessbox.workspace import GitBranchAlreadyExistsError

        async def patched_run(command, cwd=None, timeout=None):
            mock_provider._commands.append(command)
            if "rev-parse --verify origin/feat/existing" in command:
                return CommandResult(exit_code=0, stdout="abc123\n", stderr="")
            return CommandResult(exit_code=0, stdout="", stderr="")

        mock_provider.run_command = patched_run

        ws = GitRepoConfig(
            remote="https://github.com/test/repo.git",
            branch="feat/existing",
            base_branch="main",
        )
        with pytest.raises(GitBranchAlreadyExistsError) as exc_info:
            await ws.inject(mock_provider, "/workspace")

        assert exc_info.value.branch == "feat/existing"
        assert "checkout=True" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_clone_checks_out_existing_branch_when_checkout_true(self, mock_provider):
        """With checkout=True, checkout the existing remote branch."""

        async def patched_run(command, cwd=None, timeout=None):
            mock_provider._commands.append(command)
            if "rev-parse --verify origin/feat/existing" in command:
                return CommandResult(exit_code=0, stdout="abc123\n", stderr="")
            return CommandResult(exit_code=0, stdout="", stderr="")

        mock_provider.run_command = patched_run

        ws = GitRepoConfig(
            remote="https://github.com/test/repo.git",
            branch="feat/existing",
            base_branch="main",
            checkout=True,
        )
        await ws.inject(mock_provider, "/workspace")

        cmds = mock_provider._commands
        assert not any("git_create_branch:" in c for c in cmds)
        assert any("git checkout feat/existing" in c for c in cmds)

    @pytest.mark.asyncio
    async def test_clone_records_initial_sha(self, mock_provider):
        async def patched_run(command, cwd=None, timeout=None):
            mock_provider._commands.append(command)
            if "rev-parse HEAD" in command:
                return CommandResult(exit_code=0, stdout="abc123def\n", stderr="")
            return CommandResult(exit_code=0, stdout="", stderr="")

        mock_provider.run_command = patched_run

        ws = GitRepoConfig(remote="https://github.com/test/repo.git")
        await ws.inject(mock_provider, "/workspace")
        assert ws._initial_sha == "abc123def"

    @pytest.mark.asyncio
    async def test_clone_failure_fires_error_event(self, mock_provider):
        events: list[tuple[str, dict]] = []

        async def failing_clone(*args, **kwargs):
            raise RuntimeError("network timeout")

        mock_provider.git_clone = failing_clone

        ws = GitRepoConfig(
            remote="https://github.com/test/repo.git",
            on_clone_start=lambda **kw: events.append(("start", kw)),
            on_clone_complete=lambda **kw: events.append(("complete", kw)),
        )
        with pytest.raises(RuntimeError, match="git clone failed"):
            await ws.inject(mock_provider, "/workspace")

        assert len(events) == 2
        assert events[0][0] == "start"
        assert events[1][0] == "complete"
        assert events[1][1]["success"] is False


class TestGitRepoConfigExtract:
    @pytest.mark.asyncio
    async def test_extract_is_noop(self, mock_provider):
        """Extract is a no-op — system snapshots preserve .git state."""
        ws = GitRepoConfig(remote="https://github.com/test/repo.git")
        await ws.extract(mock_provider, "/workspace")
        assert len(mock_provider._commands) == 0


class TestGitRepoConfigEvents:
    @pytest.mark.asyncio
    async def test_clone_events_fire(self, mock_provider):
        events: list[tuple[str, dict]] = []
        ws = GitRepoConfig(
            remote="https://github.com/test/repo.git",
            on_clone_start=lambda **kw: events.append(("start", kw)),
            on_clone_complete=lambda **kw: events.append(("complete", kw)),
        )
        await ws.inject(mock_provider, "/workspace")

        assert len(events) == 2
        assert events[0][0] == "start"
        assert events[1][0] == "complete"
        assert events[1][1]["success"] is True


class TestGitRepoConfigDiff:
    @pytest.mark.asyncio
    async def test_diff_against_initial_sha(self, mock_provider):
        ws = GitRepoConfig(remote="https://github.com/test/repo.git")
        ws._initial_sha = "abc123"

        async def patched_run(command, cwd=None, timeout=None):
            mock_provider._commands.append(command)
            if "diff abc123" in command:
                return CommandResult(
                    exit_code=0, stdout="--- a/file.txt\n+++ b/file.txt\n", stderr=""
                )
            return CommandResult(exit_code=0, stdout="", stderr="")

        mock_provider.run_command = patched_run

        result = await ws.diff(mock_provider, "/workspace")
        assert "file.txt" in result


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


class TestGitRepoConfigDiffStat:
    @pytest.mark.asyncio
    async def test_diff_stat_returns_counts(self, mock_provider):
        ws = GitRepoConfig(remote="https://github.com/test/repo.git")
        ws._initial_sha = "abc123"

        async def patched_run(command, cwd=None, timeout=None):
            mock_provider._commands.append(command)
            if "diff --shortstat abc123" in command:
                return CommandResult(
                    exit_code=0,
                    stdout=" 3 files changed, 50 insertions(+), 12 deletions(-)\n",
                    stderr="",
                )
            return CommandResult(exit_code=0, stdout="", stderr="")

        mock_provider.run_command = patched_run

        result = await ws.diff_stat(mock_provider, "/workspace")
        assert result == {"insertions": 50, "deletions": 12}

    @pytest.mark.asyncio
    async def test_diff_stat_empty_when_no_changes(self, mock_provider):
        ws = GitRepoConfig(remote="https://github.com/test/repo.git")
        ws._initial_sha = "abc123"

        result = await ws.diff_stat(mock_provider, "/workspace")
        assert result == {"insertions": 0, "deletions": 0}

    @pytest.mark.asyncio
    async def test_diff_stat_with_clone_dir(self, mock_provider):
        ws = GitRepoConfig(remote="https://github.com/test/repo.git", clone_dir_name="tokyo")
        ws._initial_sha = "abc123"

        async def patched_run(command, cwd=None, timeout=None):
            mock_provider._commands.append(command)
            if "diff --shortstat abc123" in command:
                return CommandResult(
                    exit_code=0,
                    stdout=" 1 file changed, 5 insertions(+)\n",
                    stderr="",
                )
            return CommandResult(exit_code=0, stdout="", stderr="")

        mock_provider.run_command = patched_run

        result = await ws.diff_stat(mock_provider, "/workspace")
        assert result == {"insertions": 5, "deletions": 0}


class TestGitRepoConfigCommitCount:
    @pytest.mark.asyncio
    async def test_commit_count(self, mock_provider):
        ws = GitRepoConfig(remote="https://github.com/test/repo.git")
        ws._initial_sha = "abc123"

        async def patched_run(command, cwd=None, timeout=None):
            mock_provider._commands.append(command)
            if "rev-list --count abc123..HEAD" in command:
                return CommandResult(exit_code=0, stdout="7\n", stderr="")
            return CommandResult(exit_code=0, stdout="", stderr="")

        mock_provider.run_command = patched_run

        result = await ws.commit_count(mock_provider, "/workspace")
        assert result == 7

    @pytest.mark.asyncio
    async def test_commit_count_zero_on_failure(self, mock_provider):
        ws = GitRepoConfig(remote="https://github.com/test/repo.git")
        ws._initial_sha = "abc123"

        async def patched_run(command, cwd=None, timeout=None):
            mock_provider._commands.append(command)
            if "rev-list --count" in command:
                return CommandResult(exit_code=1, stdout="", stderr="error")
            return CommandResult(exit_code=0, stdout="", stderr="")

        mock_provider.run_command = patched_run

        result = await ws.commit_count(mock_provider, "/workspace")
        assert result == 0


class TestGitRepoConfigCreatePR:
    @pytest.mark.asyncio
    async def test_create_pr_happy_path(self, mock_provider):
        ws = GitRepoConfig(
            remote="https://github.com/test/repo.git",
            branch="tokyo",
            base_branch="main",
            auth_token="ghp_test",
        )

        async def patched_run(command, cwd=None, timeout=None):
            mock_provider._commands.append(command)
            if "gh pr create" in command:
                return CommandResult(
                    exit_code=0, stdout="https://github.com/test/repo/pull/42\n", stderr=""
                )
            return CommandResult(exit_code=0, stdout="", stderr="")

        mock_provider.run_command = patched_run

        result = await ws.create_pr(mock_provider, "/workspace", title="test PR")
        assert result["url"] == "https://github.com/test/repo/pull/42"

    @pytest.mark.asyncio
    async def test_create_pr_push_fails(self, mock_provider):
        ws = GitRepoConfig(
            remote="https://github.com/test/repo.git",
            branch="tokyo",
            base_branch="main",
        )

        async def patched_run(command, cwd=None, timeout=None):
            mock_provider._commands.append(command)
            if "push origin tokyo" in command:
                return CommandResult(exit_code=1, stdout="", stderr="rejected: non-fast-forward")
            return CommandResult(exit_code=0, stdout="", stderr="")

        mock_provider.run_command = patched_run

        with pytest.raises(RuntimeError, match="Push failed"):
            await ws.create_pr(mock_provider, "/workspace", title="test PR")

    @pytest.mark.asyncio
    async def test_create_pr_gh_fails(self, mock_provider):
        ws = GitRepoConfig(
            remote="https://github.com/test/repo.git",
            branch="tokyo",
            base_branch="main",
        )

        async def patched_run(command, cwd=None, timeout=None):
            mock_provider._commands.append(command)
            if "gh pr create" in command:
                return CommandResult(exit_code=1, stdout="", stderr="already exists")
            return CommandResult(exit_code=0, stdout="", stderr="")

        mock_provider.run_command = patched_run

        with pytest.raises(RuntimeError, match="PR creation failed"):
            await ws.create_pr(mock_provider, "/workspace", title="test PR")

    @pytest.mark.asyncio
    async def test_create_pr_shlex_escapes_title(self, mock_provider):
        ws = GitRepoConfig(
            remote="https://github.com/test/repo.git",
            branch="tokyo",
            base_branch="main",
        )

        async def patched_run(command, cwd=None, timeout=None):
            mock_provider._commands.append(command)
            if "gh pr create" in command:
                return CommandResult(
                    exit_code=0, stdout="https://github.com/test/repo/pull/1\n", stderr=""
                )
            return CommandResult(exit_code=0, stdout="", stderr="")

        mock_provider.run_command = patched_run

        result = await ws.create_pr(mock_provider, "/workspace", title="fix the user's profile")
        assert "url" in result


class TestGitRepoConfigCheckPRStatus:
    @pytest.mark.asyncio
    async def test_check_pr_status_merged(self, mock_provider):
        import json

        ws = GitRepoConfig(
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

        async def patched_run(command, cwd=None, timeout=None):
            mock_provider._commands.append(command)
            if "gh pr view" in command:
                return CommandResult(exit_code=0, stdout=pr_json, stderr="")
            return CommandResult(exit_code=0, stdout="", stderr="")

        mock_provider.run_command = patched_run

        result = await ws.check_pr_status(mock_provider, "/workspace")
        assert result["merged"] is True
        assert result["ci_status"] == "success"
        assert result["number"] == 42

    @pytest.mark.asyncio
    async def test_check_pr_status_no_pr(self, mock_provider):
        ws = GitRepoConfig(
            remote="https://github.com/test/repo.git",
            branch="tokyo",
            base_branch="main",
        )

        async def patched_run(command, cwd=None, timeout=None):
            mock_provider._commands.append(command)
            if "gh pr view" in command:
                return CommandResult(exit_code=1, stdout="", stderr="no pull requests found")
            return CommandResult(exit_code=0, stdout="", stderr="")

        mock_provider.run_command = patched_run

        result = await ws.check_pr_status(mock_provider, "/workspace")
        assert result == {}

    @pytest.mark.asyncio
    async def test_check_pr_status_ci_failure(self, mock_provider):
        import json

        ws = GitRepoConfig(
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

        async def patched_run(command, cwd=None, timeout=None):
            mock_provider._commands.append(command)
            if "gh pr view" in command:
                return CommandResult(exit_code=0, stdout=pr_json, stderr="")
            return CommandResult(exit_code=0, stdout="", stderr="")

        mock_provider.run_command = patched_run

        result = await ws.check_pr_status(mock_provider, "/workspace")
        assert result["ci_status"] == "failure"


class TestGitRepoConfigRenameBranch:
    @pytest.mark.asyncio
    async def test_rename_branch(self, mock_provider):
        ws = GitRepoConfig(
            remote="https://github.com/test/repo.git",
            branch="tokyo",
            base_branch="main",
        )

        await ws.rename_branch(mock_provider, "/workspace", "feat/new-feature")
        assert ws.branch == "feat/new-feature"

    @pytest.mark.asyncio
    async def test_rename_branch_failure(self, mock_provider):
        ws = GitRepoConfig(
            remote="https://github.com/test/repo.git",
            branch="tokyo",
            base_branch="main",
        )

        async def patched_run(command, cwd=None, timeout=None):
            mock_provider._commands.append(command)
            if "branch -m" in command:
                return CommandResult(exit_code=1, stdout="", stderr="error: refname not found")
            return CommandResult(exit_code=0, stdout="", stderr="")

        mock_provider.run_command = patched_run

        with pytest.raises(RuntimeError, match="Branch rename failed"):
            await ws.rename_branch(mock_provider, "/workspace", "bad-name")
        assert ws.branch == "tokyo"
