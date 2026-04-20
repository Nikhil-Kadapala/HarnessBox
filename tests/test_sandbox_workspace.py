"""Tests for Sandbox + Workspace integration."""

from __future__ import annotations

import pytest

from harnessbox.lifecycle import SessionState
from harnessbox.providers import CommandResult
from harnessbox.sandbox import Sandbox
from harnessbox.workspace import GitWorkspace

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
        assert sb.state == SessionState.ACTIVE

    @pytest.mark.asyncio
    async def test_workspace_none_skips_inject(self, ws_provider):
        sb = Sandbox(client=ws_provider, workspace=None)
        await sb.setup()

        cmds = ws_provider._commands
        assert not any("git" in c for c in cmds)

    @pytest.mark.asyncio
    async def test_workspace_extract_called_on_end(self, ws_provider):
        ws_provider.set_git_response(
            "status --porcelain",
            CommandResult(exit_code=0, stdout=" M file.txt\n", stderr=""),
        )

        ws = GitWorkspace(
            remote="https://github.com/test/repo.git",
            commit_on_exit=True,
        )
        sb = Sandbox(client=ws_provider, workspace=ws)
        await sb.setup()
        await sb.end()

        cmds = ws_provider._commands
        assert any("git add -A" in c for c in cmds)
        assert any("push" in c for c in cmds)
        assert sb.state.value == SessionState.MERGED.value

    @pytest.mark.asyncio
    async def test_workspace_extract_best_effort_on_kill(self, ws_provider):
        ws_provider.set_git_response(
            "status --porcelain",
            CommandResult(exit_code=0, stdout=" M file.txt\n", stderr=""),
        )

        ws = GitWorkspace(
            remote="https://github.com/test/repo.git",
            commit_on_exit=True,
        )
        sb = Sandbox(client=ws_provider, workspace=ws)
        await sb.setup()
        await sb.kill()

        assert sb.state == SessionState.FAILED

    @pytest.mark.asyncio
    async def test_push_failure_populates_unpushed_files(self, ws_provider):
        ws_provider.set_git_response(
            "status --porcelain",
            CommandResult(exit_code=0, stdout=" M file.txt\n", stderr=""),
        )
        ws_provider.set_git_response(
            "push",
            CommandResult(exit_code=1, stdout="", stderr="rejected"),
        )
        ws_provider.set_git_response(
            "diff --name-only",
            CommandResult(exit_code=0, stdout="file.txt\n", stderr=""),
        )
        ws_provider._files["/workspace/file.txt"] = "changed content"

        ws = GitWorkspace(
            remote="https://github.com/test/repo.git",
            commit_on_exit=True,
        )
        sb = Sandbox(client=ws_provider, workspace=ws)
        await sb.setup()
        await sb.end()

        assert sb.unpushed_files is not None
        assert "file.txt" in sb.unpushed_files

    @pytest.mark.asyncio
    async def test_no_push_failure_means_no_unpushed_files(self, ws_provider):
        ws_provider.set_git_response(
            "status --porcelain",
            CommandResult(exit_code=0, stdout=" M file.txt\n", stderr=""),
        )

        ws = GitWorkspace(
            remote="https://github.com/test/repo.git",
            commit_on_exit=True,
        )
        sb = Sandbox(client=ws_provider, workspace=ws)
        await sb.setup()
        await sb.end()

        assert sb.unpushed_files is None

    @pytest.mark.asyncio
    async def test_commit_on_exit_false_no_extract(self, ws_provider):
        ws = GitWorkspace(
            remote="https://github.com/test/repo.git",
            commit_on_exit=False,
        )
        sb = Sandbox(client=ws_provider, workspace=ws)
        await sb.setup()

        pre_end_cmd_count = len(ws_provider._commands)
        await sb.end()

        post_end_cmds = ws_provider._commands[pre_end_cmd_count:]
        assert not any("commit" in c for c in post_end_cmds)
        assert not any("push" in c for c in post_end_cmds)

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
            assert sb.state == SessionState.ACTIVE
        assert sb.state.value == SessionState.FAILED.value
