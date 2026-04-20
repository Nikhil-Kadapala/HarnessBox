"""Tests for harnessbox.sandbox — Sandbox class."""

from __future__ import annotations

import pytest

from harnessbox.lifecycle import InvalidTransitionError, SessionState
from harnessbox.sandbox import Sandbox
from harnessbox.security.policy import SecurityPolicy


class TestConstruction:
    def test_with_provider_instance(self, mock_provider):
        sb = Sandbox(client=mock_provider, harness="claude-code")
        assert sb.provider is mock_provider
        assert sb.state == SessionState.STARTING

    def test_default_agent_type_is_claude_code(self, mock_provider):
        sb = Sandbox(client=mock_provider)
        assert sb.harness_config.name == "claude-code"

    def test_custom_agent_type(self, mock_provider):
        sb = Sandbox(client=mock_provider, harness="codex")
        assert sb.harness_config.name == "codex"

    def test_invalid_client_type_raises(self):
        with pytest.raises(TypeError, match="SandboxProvider"):
            Sandbox(client=12345)  # type: ignore[arg-type]

    def test_unknown_agent_type_raises(self, mock_provider):
        with pytest.raises(KeyError, match="Unknown harness type"):
            Sandbox(client=mock_provider, harness="nonexistent")

    def test_sandbox_id_none_before_setup(self, mock_provider):
        sb = Sandbox(client=mock_provider)
        assert sb.sandbox_id is None


class TestSetup:
    @pytest.mark.asyncio
    async def test_transitions_to_active(self, mock_provider):
        sb = Sandbox(client=mock_provider)
        await sb.setup()
        assert sb.state == SessionState.ACTIVE
        assert sb.sandbox_id == "mock-sandbox-123"

    @pytest.mark.asyncio
    async def test_creates_default_dirs(self, mock_provider):
        sb = Sandbox(client=mock_provider, harness="claude-code")
        await sb.setup()
        assert "/workspace/user_input" in mock_provider._dirs
        assert "/workspace/output" in mock_provider._dirs
        assert "/workspace/.claude" in mock_provider._dirs
        assert "/workspace/.claude/hooks" in mock_provider._dirs

    @pytest.mark.asyncio
    async def test_creates_user_dirs(self, mock_provider):
        sb = Sandbox(
            client=mock_provider,
            dirs=["/workspace/custom_dir"],
        )
        await sb.setup()
        assert "/workspace/custom_dir" in mock_provider._dirs

    @pytest.mark.asyncio
    async def test_writes_user_files(self, mock_provider):
        sb = Sandbox(
            client=mock_provider,
            files={"/workspace/test.txt": "hello"},
        )
        await sb.setup()
        assert mock_provider._files["/workspace/test.txt"] == "hello"

    @pytest.mark.asyncio
    async def test_system_prompt_via_setup(self, mock_provider):
        sb = Sandbox(client=mock_provider, harness="claude-code")
        await sb.setup(system_prompt="You are a test assistant.")
        assert mock_provider._files["/workspace/CLAUDE.md"] == "You are a test assistant."

    @pytest.mark.asyncio
    async def test_security_config_injected(self, mock_provider):
        policy = SecurityPolicy(denied_tools=["WebFetch"], deny_network=True)
        sb = Sandbox(client=mock_provider, security_policy=policy)
        await sb.setup()
        assert "/workspace/.claude/settings.json" in mock_provider._files
        assert "/workspace/.claude/hooks/guard_bash.py" in mock_provider._files

    @pytest.mark.asyncio
    async def test_no_security_config_without_policy(self, mock_provider):
        sb = Sandbox(client=mock_provider)
        await sb.setup()
        assert "/workspace/.claude/settings.json" not in mock_provider._files

    @pytest.mark.asyncio
    async def test_hook_chmod_called(self, mock_provider):
        policy = SecurityPolicy()
        sb = Sandbox(client=mock_provider, security_policy=policy)
        await sb.setup()
        chmod_cmds = [c for c in mock_provider._commands if "chmod" in c]
        assert len(chmod_cmds) == 1
        assert "guard_bash.py" in chmod_cmds[0]

    @pytest.mark.asyncio
    async def test_env_vars_passed_to_provider(self, mock_provider):
        sb = Sandbox(
            client=mock_provider,
            env_vars={"FOO": "bar"},
        )
        await sb.setup()
        assert mock_provider._env_vars == {"FOO": "bar"}

    @pytest.mark.asyncio
    async def test_setup_script_runs_after_files(self, mock_provider):
        sb = Sandbox(
            client=mock_provider,
            setup_script="npm install",
        )
        await sb.setup()
        assert "npm install" in mock_provider._commands

    @pytest.mark.asyncio
    async def test_setup_script_failure_raises(self, mock_provider):
        from harnessbox.providers import CommandResult

        original_run = mock_provider.run_command

        async def failing_run(command, cwd=None, timeout=None):
            if command == "npm install":
                mock_provider._commands.append(command)
                return CommandResult(exit_code=1, stdout="", stderr="npm ERR! missing package.json")
            return await original_run(command, cwd=cwd, timeout=timeout)

        mock_provider.run_command = failing_run
        sb = Sandbox(client=mock_provider, setup_script="npm install")
        with pytest.raises(RuntimeError, match="Setup script failed"):
            await sb.setup()

    @pytest.mark.asyncio
    async def test_setup_script_none_skips(self, mock_provider):
        sb = Sandbox(client=mock_provider, setup_script=None)
        await sb.setup()
        assert not any("npm" in c for c in mock_provider._commands)


class TestKill:
    @pytest.mark.asyncio
    async def test_transitions_to_failed(self, mock_provider):
        sb = Sandbox(client=mock_provider)
        await sb.setup()
        await sb.kill()
        assert sb.state == SessionState.FAILED

    @pytest.mark.asyncio
    async def test_idempotent_from_failed(self, mock_provider):
        sb = Sandbox(client=mock_provider)
        await sb.setup()
        await sb.kill()
        await sb.kill()
        assert sb.state == SessionState.FAILED

    @pytest.mark.asyncio
    async def test_idempotent_from_merged(self, mock_provider):
        sb = Sandbox(client=mock_provider)
        await sb.setup()
        await sb.end()
        await sb.kill()
        assert sb.state == SessionState.MERGED


class TestPauseResume:
    @pytest.mark.asyncio
    async def test_pause_transitions(self, mock_provider):
        sb = Sandbox(client=mock_provider)
        await sb.setup()
        sid = await sb.pause()
        assert sb.state == SessionState.PAUSED
        assert sid == "mock-sandbox-123"

    @pytest.mark.asyncio
    async def test_resume_transitions(self, mock_provider):
        sb = Sandbox(client=mock_provider)
        await sb.setup()
        await sb.pause()
        await sb.resume("mock-sandbox-123")
        assert sb.state == SessionState.ACTIVE

    @pytest.mark.asyncio
    async def test_pause_from_starting_raises(self, mock_provider):
        sb = Sandbox(client=mock_provider)
        with pytest.raises(InvalidTransitionError):
            await sb.pause()


class TestEnd:
    @pytest.mark.asyncio
    async def test_end_transitions_to_merged(self, mock_provider):
        sb = Sandbox(client=mock_provider)
        await sb.setup()
        await sb.end()
        assert sb.state == SessionState.MERGED

    @pytest.mark.asyncio
    async def test_end_from_starting_raises(self, mock_provider):
        sb = Sandbox(client=mock_provider)
        with pytest.raises(InvalidTransitionError):
            await sb.end()


class TestRunPrompt:
    @pytest.mark.asyncio
    async def test_yields_stream_lines(self, mock_provider):
        mock_provider._stream_lines = ['{"type": "start"}', '{"type": "end"}']
        sb = Sandbox(client=mock_provider)
        await sb.setup()

        collected = []
        async for line in sb.run_prompt("test prompt"):
            collected.append(line)

        assert collected == ['{"type": "start"}', '{"type": "end"}']

    @pytest.mark.asyncio
    async def test_command_uses_agent_template(self, mock_provider):
        mock_provider._stream_lines = []
        sb = Sandbox(client=mock_provider, harness="claude-code")
        await sb.setup()

        async for _ in sb.run_prompt("hello"):
            pass

        stream_cmd = [c for c in mock_provider._commands if "claude" in c]
        assert len(stream_cmd) == 1
        assert "--dangerously-skip-permissions" in stream_cmd[0]
        assert '"hello"' in stream_cmd[0]

    @pytest.mark.asyncio
    async def test_raises_in_non_active_state(self, mock_provider):
        sb = Sandbox(client=mock_provider)
        with pytest.raises(RuntimeError, match="Cannot run prompt"):
            async for _ in sb.run_prompt("test"):
                pass


class TestInteractive:
    @pytest.mark.asyncio
    async def test_start_interactive_returns_pid(self, mock_provider):
        sb = Sandbox(client=mock_provider)
        await sb.setup()
        pid = await sb.start_interactive()
        assert pid == 42

    @pytest.mark.asyncio
    async def test_send_message_after_start(self, mock_provider):
        sb = Sandbox(client=mock_provider)
        await sb.setup()
        await sb.start_interactive()
        await sb.send_message("hello")
        stdin_cmds = [c for c in mock_provider._commands if c.startswith("stdin:")]
        assert len(stdin_cmds) == 1
        assert "hello" in stdin_cmds[0]

    @pytest.mark.asyncio
    async def test_send_message_without_start_raises(self, mock_provider):
        sb = Sandbox(client=mock_provider)
        await sb.setup()
        with pytest.raises(RuntimeError, match="Interactive mode not started"):
            await sb.send_message("hello")

    @pytest.mark.asyncio
    async def test_start_interactive_in_non_active_raises(self, mock_provider):
        sb = Sandbox(client=mock_provider)
        with pytest.raises(RuntimeError, match="Cannot start interactive"):
            await sb.start_interactive()


class TestFileIO:
    @pytest.mark.asyncio
    async def test_write_and_read_file(self, mock_provider):
        sb = Sandbox(client=mock_provider)
        await sb.setup()
        await sb.write_file("/workspace/test.txt", "content")
        result = await sb.read_file("/workspace/test.txt")
        assert result == "content"

    @pytest.mark.asyncio
    async def test_write_files_batch(self, mock_provider):
        sb = Sandbox(client=mock_provider)
        await sb.setup()
        await sb.write_files({"/workspace/a.txt": "a", "/workspace/b.txt": "b"})
        assert mock_provider._files["/workspace/a.txt"] == "a"
        assert mock_provider._files["/workspace/b.txt"] == "b"

    @pytest.mark.asyncio
    async def test_make_dir(self, mock_provider):
        sb = Sandbox(client=mock_provider)
        await sb.setup()
        await sb.make_dir("/workspace/new_dir")
        assert "/workspace/new_dir" in mock_provider._dirs


class TestRunCommand:
    @pytest.mark.asyncio
    async def test_run_command(self, mock_provider):
        sb = Sandbox(client=mock_provider)
        await sb.setup()
        result = await sb.run_command("ls -la")
        assert result.exit_code == 0
        assert "ls -la" in mock_provider._commands


class TestContextManager:
    @pytest.mark.asyncio
    async def test_context_manager_kills_on_exit(self, mock_provider):
        async with Sandbox(client=mock_provider) as sb:
            await sb.setup()
            assert sb.state == SessionState.ACTIVE
        assert sb.state.value == SessionState.FAILED.value

    @pytest.mark.asyncio
    async def test_context_manager_kills_on_exception(self, mock_provider):
        with pytest.raises(ValueError, match="test error"):
            async with Sandbox(client=mock_provider) as sb:
                await sb.setup()
                raise ValueError("test error")
        assert sb.state.value == SessionState.FAILED.value
