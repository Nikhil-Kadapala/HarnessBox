"""Tests for Sandbox + Workspace integration."""

from __future__ import annotations

import pytest

from harnessbox.lifecycle import RuntimeState
from harnessbox.providers import CommandResult
from harnessbox.sandbox import Sandbox
from harnessbox.workspace import GitRepoConfig
from tests.conftest import MockProvider


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
        if "rev-parse --verify origin/" in command:
            return CommandResult(exit_code=128, stdout="", stderr="fatal: not a valid ref")
        return CommandResult(exit_code=0, stdout="", stderr="")


@pytest.fixture
def ws_provider():
    return _WorkspaceMockProvider()


class TestSandboxWithWorkspace:
    @pytest.mark.asyncio
    async def test_workspace_inject_called_on_setup(self, ws_provider):
        ws = GitRepoConfig(remote="https://github.com/test/repo.git")
        sb = Sandbox(client=ws_provider, workspace=ws)
        await sb.setup()

        cmds = ws_provider._commands
        assert any("git_clone:" in c for c in cmds)
        assert any("git_configure_user:" in c for c in cmds)
        assert sb.state == RuntimeState.ACTIVE

    @pytest.mark.asyncio
    async def test_workspace_none_skips_inject(self, ws_provider):
        sb = Sandbox(client=ws_provider, workspace=None)
        await sb.setup()

        cmds = ws_provider._commands
        assert not any("git" in c for c in cmds)

    @pytest.mark.asyncio
    async def test_end_does_not_commit_or_push(self, ws_provider):
        ws = GitRepoConfig(remote="https://github.com/test/repo.git")
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
        ws = GitRepoConfig(remote="https://github.com/test/repo.git")
        sb = Sandbox(client=ws_provider, workspace=ws)
        await sb.setup()

        pre_kill_cmd_count = len(ws_provider._commands)
        await sb.kill()

        post_kill_cmds = ws_provider._commands[pre_kill_cmd_count:]
        assert not any("commit" in c for c in post_kill_cmds)
        assert not any("push" in c for c in post_kill_cmds)
        assert sb.state == RuntimeState.DEAD

    @pytest.mark.asyncio
    async def test_manifest_files_not_injected_on_slim_setup(self, ws_provider):
        """Slim create clones git but does not write harness/agent files."""
        ws = GitRepoConfig(
            remote="https://github.com/test/repo.git",
            clone_dir_name="alexandria",
        )
        from harnessbox.security.policy import SecurityPolicy

        sb = Sandbox(
            client=ws_provider,
            workspace=ws,
            harness="claude-code",
            security_policy=SecurityPolicy(),
        )
        await sb.setup()

        written_files = list(ws_provider._files.keys())
        assert not any(".claude/" in f for f in written_files)
        assert not any(f.endswith("CLAUDE.md") for f in written_files)

    @pytest.mark.asyncio
    async def test_inject_failure_propagates(self, ws_provider):
        async def failing_clone(*args, **kwargs):
            raise RuntimeError("Authentication failed")

        ws_provider.git_clone = failing_clone

        ws = GitRepoConfig(remote="https://github.com/test/repo.git")
        sb = Sandbox(client=ws_provider, workspace=ws)

        with pytest.raises(RuntimeError, match="git clone failed"):
            await sb.setup()

    @pytest.mark.asyncio
    async def test_context_manager_with_workspace(self, ws_provider):
        ws = GitRepoConfig(remote="https://github.com/test/repo.git")
        async with Sandbox(client=ws_provider, workspace=ws) as sb:
            await sb.setup()
            assert sb.state == RuntimeState.ACTIVE
        assert sb.state.value == RuntimeState.DEAD.value


class TestGitRepoConfigAlias:
    def test_can_instantiate_via_alias(self):
        ws = GitRepoConfig(remote="https://github.com/test/repo.git")
        assert isinstance(ws, GitRepoConfig)


class TestSandboxGitFacade:
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
            await sb.diff_stat()

        with pytest.raises(RuntimeError, match="No git workspace configured"):
            await sb.commit_count()
