"""Tests for Sandbox + Workspace integration."""

from __future__ import annotations

import pytest

from harnessbox.lifecycle import RuntimeState
from harnessbox.providers import CommandResult
from harnessbox.sandbox import Sandbox
from harnessbox.workspace import GitRepoConfig, GitWorkspace

from .conftest import MockProvider


class _WorkspaceMockProvider(MockProvider):
    """MockProvider that tracks git commands for workspace testing."""

    def __init__(self) -> None:
        super().__init__()
        self._git_responses: dict[str, CommandResult] = {}

    def set_git_response(self, fragment: str, result: CommandResult) -> None:
        self._git_responses[fragment] = result

    async def run_command(self, command, cwd=None, timeout=None):
        self._commands.append(command)
        for fragment, result in self._git_responses.items():
            if fragment in command:
                return result
        return CommandResult(exit_code=0, stdout="", stderr="")


@pytest.fixture
def ws_provider():
    return _WorkspaceMockProvider()


class TestSandboxWithWorkspace:
    @pytest.mark.asyncio
    async def test_workspace_inject_called_on_setup(self, ws_provider):
        ws = GitWorkspace(remote="https://github.com/test/repo.git")
        sb = Sandbox(client=ws_provider, workspace=ws)
        await sb.setup()

        cmds = ws_provider._commands
        assert any("git init" in c for c in cmds)
        assert any("git fetch" in c for c in cmds)
        assert sb.state == RuntimeState.ACTIVE

    @pytest.mark.asyncio
    async def test_workspace_none_skips_inject(self, ws_provider):
        sb = Sandbox(client=ws_provider, workspace=None)
        await sb.setup()

        cmds = ws_provider._commands
        assert not any("git" in c for c in cmds)

    @pytest.mark.asyncio
    async def test_end_does_not_commit_or_push(self, ws_provider):
        ws = GitWorkspace(remote="https://github.com/test/repo.git")
        sb = Sandbox(client=ws_provider, workspace=ws)
        await sb.setup()

        pre_end_cmd_count = len(ws_provider._commands)
        await sb.end()

        post_end_cmds = ws_provider._commands[pre_end_cmd_count:]
        assert not any("commit" in c for c in post_end_cmds)
        assert not any("push" in c for c in post_end_cmds)
        assert sb.state.value == RuntimeState.ENDED.value

    @pytest.mark.asyncio
    async def test_kill_does_not_commit_or_push(self, ws_provider):
        ws = GitWorkspace(remote="https://github.com/test/repo.git")
        sb = Sandbox(client=ws_provider, workspace=ws)
        await sb.setup()

        pre_kill_cmd_count = len(ws_provider._commands)
        await sb.kill()

        post_kill_cmds = ws_provider._commands[pre_kill_cmd_count:]
        assert not any("commit" in c for c in post_kill_cmds)
        assert not any("push" in c for c in post_kill_cmds)
        assert sb.state == RuntimeState.FAILED

    @pytest.mark.asyncio
    async def test_manifest_files_go_into_cloned_directory(self, ws_provider):
        """Verify manifest files (CLAUDE.md, .claude/) are injected into the cloned repo directory."""
        ws = GitWorkspace(
            remote="https://github.com/test/repo.git",
            clone_dir_name="alexandria",
        )
        from harnessbox.security.policy import SecurityPolicy

        sb = Sandbox(
            client=ws_provider,
            workspace=ws,
            harness="claude-code",
            security_policy=SecurityPolicy(),  # Add security policy to trigger settings.json
        )
        await sb.setup()

        # Check that manifest files were written to /workspace/alexandria/, not /workspace/
        written_files = list(ws_provider._files.keys())

        # All manifest files should be in /workspace/alexandria/
        assert any("/workspace/alexandria/.claude/" in f for f in written_files), (
            f"Expected .claude/ in /workspace/alexandria/, got: {written_files}"
        )

        # No manifest files should be at workspace root
        assert not any(
            f.startswith("/workspace/.claude/") and "/alexandria/" not in f for f in written_files
        ), (
            f"Settings should not be at workspace root, found: {[f for f in written_files if f.startswith('/workspace/.claude/')]}"
        )

    @pytest.mark.asyncio
    async def test_inject_failure_propagates(self, ws_provider):
        ws_provider.set_git_response(
            "fetch",
            CommandResult(exit_code=128, stdout="", stderr="Authentication failed"),
        )

        ws = GitWorkspace(remote="https://github.com/test/repo.git")
        sb = Sandbox(client=ws_provider, workspace=ws)

        with pytest.raises(RuntimeError, match="git clone failed"):
            await sb.setup()

    @pytest.mark.asyncio
    async def test_context_manager_with_workspace(self, ws_provider):
        ws = GitWorkspace(remote="https://github.com/test/repo.git")
        async with Sandbox(client=ws_provider, workspace=ws) as sb:
            await sb.setup()
            assert sb.state == RuntimeState.ACTIVE
        assert sb.state.value == RuntimeState.FAILED.value


class TestGitRepoConfigAlias:
    def test_alias_is_same_class(self):
        assert GitWorkspace is GitRepoConfig

    def test_can_instantiate_via_alias(self):
        ws = GitWorkspace(remote="https://github.com/test/repo.git")
        assert isinstance(ws, GitRepoConfig)


class TestSandboxGitFacade:
    @pytest.mark.asyncio
    async def test_rename_branch_delegates(self, ws_provider):
        ws_provider.set_git_response(
            "branch -m",
            CommandResult(exit_code=0, stdout="", stderr=""),
        )
        ws = GitRepoConfig(remote="https://github.com/test/repo.git", branch="old-branch")
        sb = Sandbox(client=ws_provider, workspace=ws)
        await sb.setup()

        await sb.rename_branch("new-branch")
        assert ws.branch == "new-branch"
        assert any("branch -m" in c for c in ws_provider._commands)

    @pytest.mark.asyncio
    async def test_diff_stat_delegates(self, ws_provider):
        ws_provider.set_git_response(
            "diff --shortstat",
            CommandResult(
                exit_code=0,
                stdout=" 3 files changed, 15 insertions(+), 5 deletions(-)\n",
                stderr="",
            ),
        )
        ws = GitRepoConfig(remote="https://github.com/test/repo.git")
        sb = Sandbox(client=ws_provider, workspace=ws)
        await sb.setup()

        stat = await sb.diff_stat()
        assert stat == {"insertions": 15, "deletions": 5}

    @pytest.mark.asyncio
    async def test_commit_count_delegates(self, ws_provider):
        ws_provider.set_git_response(
            "rev-list --count",
            CommandResult(exit_code=0, stdout="7\n", stderr=""),
        )
        ws = GitRepoConfig(remote="https://github.com/test/repo.git")
        sb = Sandbox(client=ws_provider, workspace=ws)
        await sb.setup()

        count = await sb.commit_count()
        assert count == 7

    @pytest.mark.asyncio
    async def test_facade_raises_without_workspace(self, ws_provider):
        sb = Sandbox(client=ws_provider, workspace=None)
        await sb.setup()

        with pytest.raises(RuntimeError, match="No git workspace configured"):
            await sb.rename_branch("x")

        with pytest.raises(RuntimeError, match="No git workspace configured"):
            await sb.diff_stat()

        with pytest.raises(RuntimeError, match="No git workspace configured"):
            await sb.commit_count()

    @pytest.mark.asyncio
    async def test_create_pr_delegates(self, ws_provider):
        ws_provider.set_git_response(
            "gh pr create",
            CommandResult(exit_code=0, stdout="https://github.com/test/repo/pull/1\n", stderr=""),
        )
        ws = GitRepoConfig(
            remote="https://github.com/test/repo.git",
            branch="feat",
            base_branch="main",
            auth_token="tok",
        )
        sb = Sandbox(client=ws_provider, workspace=ws)
        await sb.setup()

        result = await sb.create_pr("Add feature", "Description")
        assert result["url"] == "https://github.com/test/repo/pull/1"

    @pytest.mark.asyncio
    async def test_check_pr_status_delegates(self, ws_provider):
        import json

        pr_json = json.dumps({
            "state": "OPEN",
            "merged": False,
            "url": "https://github.com/test/repo/pull/1",
            "number": 1,
            "statusCheckRollup": [{"conclusion": "SUCCESS"}],
        })
        ws_provider.set_git_response(
            "gh pr view",
            CommandResult(exit_code=0, stdout=pr_json, stderr=""),
        )
        ws = GitRepoConfig(
            remote="https://github.com/test/repo.git",
            branch="feat",
            auth_token="tok",
        )
        sb = Sandbox(client=ws_provider, workspace=ws)
        await sb.setup()

        status = await sb.check_pr_status()
        assert status["state"] == "open"
        assert status["ci_status"] == "success"
        assert status["number"] == 1
