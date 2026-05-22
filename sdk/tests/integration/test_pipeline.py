"""Tests for harnessbox.config.pipeline — setup pipeline execution."""

from __future__ import annotations

import pytest

from harnessbox.config.harness import get_harness_type
from harnessbox.config.pipeline import (
    SetupContext,
    SetupPipeline,
    SetupStep,
    build_setup_pipeline,
)
from harnessbox.security.policy import SecurityPolicy
from tests.conftest import MockProvider


class TestSetupContext:
    def test_defaults(self):
        provider = MockProvider()
        ctx = SetupContext(
            provider=provider,
            harness_config=get_harness_type("claude-code"),
        )
        assert ctx.manifest is None
        assert ctx.cwd == ""
        assert ctx.manifest_target_dir == ""
        assert ctx.timings == {}
        assert ctx.setup_script is None
        assert ctx.dirs == []
        assert ctx.files == {}

    def test_carries_state(self):
        provider = MockProvider()
        ctx = SetupContext(
            provider=provider,
            harness_config=get_harness_type("claude-code"),
            env_vars={"API_KEY": "test"},
            setup_script="npm install",
        )
        assert ctx.env_vars == {"API_KEY": "test"}
        assert ctx.setup_script == "npm install"


class TestSetupStep:
    def test_frozen(self):
        async def noop(ctx: SetupContext) -> None:
            pass

        step = SetupStep(name="test", execute=noop)
        assert step.name == "test"
        assert step.skip_if is None


class TestSetupPipeline:
    @pytest.mark.asyncio
    async def test_executes_steps_in_order(self):
        order: list[str] = []

        async def step_a(ctx: SetupContext) -> None:
            order.append("a")

        async def step_b(ctx: SetupContext) -> None:
            order.append("b")

        async def step_c(ctx: SetupContext) -> None:
            order.append("c")

        pipeline = SetupPipeline(
            [
                SetupStep(name="a", execute=step_a),
                SetupStep(name="b", execute=step_b),
                SetupStep(name="c", execute=step_c),
            ]
        )

        provider = MockProvider()
        ctx = SetupContext(provider=provider, harness_config=get_harness_type("claude-code"))
        await pipeline.execute(ctx)

        assert order == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_records_timings(self):
        async def noop(ctx: SetupContext) -> None:
            pass

        pipeline = SetupPipeline(
            [
                SetupStep(name="fast_step", execute=noop),
            ]
        )

        provider = MockProvider()
        ctx = SetupContext(provider=provider, harness_config=get_harness_type("claude-code"))
        timings = await pipeline.execute(ctx)

        assert "fast_step" in timings
        assert "_total" in timings
        assert timings["fast_step"] >= 0
        assert timings["_total"] >= 0

    @pytest.mark.asyncio
    async def test_skip_if_respected(self):
        order: list[str] = []

        async def step_a(ctx: SetupContext) -> None:
            order.append("a")

        async def step_b(ctx: SetupContext) -> None:
            order.append("b")

        pipeline = SetupPipeline(
            [
                SetupStep(name="a", execute=step_a, skip_if=lambda ctx: True),
                SetupStep(name="b", execute=step_b),
            ]
        )

        provider = MockProvider()
        ctx = SetupContext(provider=provider, harness_config=get_harness_type("claude-code"))
        await pipeline.execute(ctx)

        assert order == ["b"]
        assert ctx.timings["a"] == 0.0

    @pytest.mark.asyncio
    async def test_error_halts_pipeline(self):
        order: list[str] = []

        async def step_ok(ctx: SetupContext) -> None:
            order.append("ok")

        async def step_fail(ctx: SetupContext) -> None:
            raise RuntimeError("boom")

        async def step_after(ctx: SetupContext) -> None:
            order.append("after")

        pipeline = SetupPipeline(
            [
                SetupStep(name="ok", execute=step_ok),
                SetupStep(name="fail", execute=step_fail),
                SetupStep(name="after", execute=step_after),
            ]
        )

        provider = MockProvider()
        ctx = SetupContext(provider=provider, harness_config=get_harness_type("claude-code"))

        with pytest.raises(RuntimeError, match="boom"):
            await pipeline.execute(ctx)

        assert order == ["ok"]

    @pytest.mark.asyncio
    async def test_context_state_propagates_between_steps(self):
        async def step_write(ctx: SetupContext) -> None:
            ctx.cwd = "/workspace/myrepo"

        async def step_read(ctx: SetupContext) -> None:
            assert ctx.cwd == "/workspace/myrepo"

        pipeline = SetupPipeline(
            [
                SetupStep(name="write", execute=step_write),
                SetupStep(name="read", execute=step_read),
            ]
        )

        provider = MockProvider()
        ctx = SetupContext(provider=provider, harness_config=get_harness_type("claude-code"))
        await pipeline.execute(ctx)

    def test_step_names(self):
        async def noop(ctx: SetupContext) -> None:
            pass

        pipeline = SetupPipeline(
            [
                SetupStep(name="a", execute=noop),
                SetupStep(name="b", execute=noop),
                SetupStep(name="c", execute=noop),
            ]
        )

        assert pipeline.step_names() == ["a", "b", "c"]

    def test_dry_run_respects_skip_if(self):
        async def noop(ctx: SetupContext) -> None:
            pass

        pipeline = SetupPipeline(
            [
                SetupStep(name="always", execute=noop),
                SetupStep(name="skipped", execute=noop, skip_if=lambda ctx: True),
                SetupStep(
                    name="conditional", execute=noop, skip_if=lambda ctx: ctx.workspace is None
                ),
            ]
        )

        provider = MockProvider()
        ctx = SetupContext(provider=provider, harness_config=get_harness_type("claude-code"))
        result = pipeline.dry_run(ctx)

        assert result == ["always"]


class TestBuildSetupPipeline:
    def test_default_pipeline_step_names(self):
        pipeline = build_setup_pipeline()
        names = pipeline.step_names()
        assert names == [
            "create_sandbox",
            "check_tools",
            "create_workspace_root",
            "inject_workspace",
            "build_manifest",
            "create_directories",
            "inject_files",
            "set_hook_permissions",
            "run_setup_script",
        ]

    def test_extra_steps_appended(self):
        async def custom(ctx: SetupContext) -> None:
            pass

        pipeline = build_setup_pipeline(extra_steps=[SetupStep(name="custom_step", execute=custom)])
        names = pipeline.step_names()
        assert names[-1] == "custom_step"

    @pytest.mark.asyncio
    async def test_full_pipeline_with_mock_provider(self):
        """Run the full default pipeline against MockProvider."""
        provider = MockProvider()
        ctx = SetupContext(
            provider=provider,
            harness_config=get_harness_type("claude-code"),
            env_vars={"TEST": "1"},
        )
        pipeline = build_setup_pipeline()
        await pipeline.execute(ctx)

        assert provider._sandbox_id == "mock-sandbox-123"
        assert "/workspace" in provider._dirs
        assert ctx.manifest is not None
        assert ctx.manifest_target_dir == "/workspace"

    @pytest.mark.asyncio
    async def test_pipeline_with_security_policy(self):
        """Security policy produces settings and hook files."""
        provider = MockProvider()
        policy = SecurityPolicy(denied_tools=["WebFetch"], deny_network=True)
        ctx = SetupContext(
            provider=provider,
            harness_config=get_harness_type("claude-code"),
            security_policy=policy,
        )
        pipeline = build_setup_pipeline()
        await pipeline.execute(ctx)

        assert "/workspace/.claude/settings.json" in provider._files
        assert "/workspace/.claude/hooks/guard_bash.py" in provider._files
        chmod_cmds = [c for c in provider._commands if "chmod" in c]
        assert len(chmod_cmds) == 1

    @pytest.mark.asyncio
    async def test_pipeline_with_setup_script(self):
        """Setup script runs at the end."""
        provider = MockProvider()
        ctx = SetupContext(
            provider=provider,
            harness_config=get_harness_type("claude-code"),
            setup_script="npm install",
        )
        pipeline = build_setup_pipeline()
        await pipeline.execute(ctx)

        assert "npm install" in provider._commands

    @pytest.mark.asyncio
    async def test_pipeline_setup_script_failure(self):
        """Setup script failure raises RuntimeError."""
        from harnessbox.providers import CommandResult

        provider = MockProvider()
        original_run = provider.run_command

        async def failing_run(command, cwd=None, timeout=None):
            if command == "npm install":
                provider._commands.append(command)
                return CommandResult(exit_code=1, stdout="", stderr="npm ERR!")
            return await original_run(command, cwd=cwd, timeout=timeout)

        provider.run_command = failing_run  # type: ignore[assignment]

        ctx = SetupContext(
            provider=provider,
            harness_config=get_harness_type("claude-code"),
            setup_script="npm install",
        )
        pipeline = build_setup_pipeline()

        with pytest.raises(RuntimeError, match="Setup script failed"):
            await pipeline.execute(ctx)

    @pytest.mark.asyncio
    async def test_pipeline_with_system_prompt(self):
        """System prompt is written as CLAUDE.md."""
        provider = MockProvider()
        ctx = SetupContext(
            provider=provider,
            harness_config=get_harness_type("claude-code"),
            system_prompt="You are a test agent.",
        )
        pipeline = build_setup_pipeline()
        await pipeline.execute(ctx)

        assert provider._files["/workspace/CLAUDE.md"] == "You are a test agent."

    @pytest.mark.asyncio
    async def test_pipeline_with_user_files(self):
        """User files are injected via manifest."""
        provider = MockProvider()
        ctx = SetupContext(
            provider=provider,
            harness_config=get_harness_type("claude-code"),
            files={"/workspace/data.json": '{"key": "value"}'},
        )
        pipeline = build_setup_pipeline()
        await pipeline.execute(ctx)

        assert provider._files["/workspace/data.json"] == '{"key": "value"}'

    @pytest.mark.asyncio
    async def test_pipeline_skips_workspace_when_none(self):
        """inject_workspace step is skipped when no workspace configured."""
        provider = MockProvider()
        ctx = SetupContext(
            provider=provider,
            harness_config=get_harness_type("claude-code"),
        )
        pipeline = build_setup_pipeline()
        result = pipeline.dry_run(ctx)

        assert "inject_workspace" not in result

    @pytest.mark.asyncio
    async def test_pipeline_skips_hooks_without_policy(self):
        """set_hook_permissions is skipped without a security policy."""
        provider = MockProvider()
        ctx = SetupContext(
            provider=provider,
            harness_config=get_harness_type("claude-code"),
        )
        pipeline = build_setup_pipeline()
        result = pipeline.dry_run(ctx)

        assert "set_hook_permissions" not in result


class TestSandboxDryRun:
    """Test the Sandbox.dry_run() method that wraps pipeline.dry_run()."""

    def test_dry_run_returns_step_names(self):
        from harnessbox.sandbox import Sandbox

        provider = MockProvider()
        sb = Sandbox(client=provider, harness="claude-code")
        steps = sb.dry_run()

        assert "create_sandbox" in steps
        assert "build_manifest" in steps
        assert "inject_workspace" not in steps  # no workspace configured

    def test_dry_run_includes_setup_script_when_configured(self):
        from harnessbox.sandbox import Sandbox

        provider = MockProvider()
        sb = Sandbox(client=provider, harness="claude-code", setup_script="npm install")
        steps = sb.dry_run()

        assert "run_setup_script" in steps

    def test_dry_run_excludes_setup_script_when_none(self):
        from harnessbox.sandbox import Sandbox

        provider = MockProvider()
        sb = Sandbox(client=provider, harness="claude-code")
        steps = sb.dry_run()

        assert "run_setup_script" not in steps

    def test_dry_run_includes_hooks_with_policy(self):
        from harnessbox.sandbox import Sandbox

        provider = MockProvider()
        sb = Sandbox(
            client=provider,
            harness="claude-code",
            security_policy=SecurityPolicy(),
        )
        steps = sb.dry_run()

        assert "set_hook_permissions" in steps
