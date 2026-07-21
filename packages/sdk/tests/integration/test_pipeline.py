"""Tests for harnessbox.config.pipeline — setup pipeline execution."""

from __future__ import annotations

import pytest

from harnessbox.config.harness import get_harness_type
from harnessbox.config.pipeline import (
    InitializeContext,
    InitializeSandbox,
    InitializeStep,
    initialize_sandbox,
)
from harnessbox.security.policy import SecurityPolicy
from tests.conftest import MockProvider


class TestInitializeContext:
    def test_defaults(self):
        provider = MockProvider()
        ctx = InitializeContext(
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
        ctx = InitializeContext(
            provider=provider,
            harness_config=get_harness_type("claude-code"),
            env_vars={"API_KEY": "test"},
            setup_script="npm install",
        )
        assert ctx.env_vars == {"API_KEY": "test"}
        assert ctx.setup_script == "npm install"


class TestInitializeStep:
    def test_frozen(self):
        async def noop(ctx: InitializeContext) -> None:
            pass

        step = InitializeStep(name="test", execute=noop)
        assert step.name == "test"
        assert step.skip_if is None


class TestInitializeSandbox:
    @pytest.mark.asyncio
    async def test_executes_steps_in_order(self):
        order: list[str] = []

        async def step_a(ctx: InitializeContext) -> None:
            order.append("a")

        async def step_b(ctx: InitializeContext) -> None:
            order.append("b")

        async def step_c(ctx: InitializeContext) -> None:
            order.append("c")

        pipeline = InitializeSandbox(
            [
                InitializeStep(name="a", execute=step_a),
                InitializeStep(name="b", execute=step_b),
                InitializeStep(name="c", execute=step_c),
            ]
        )

        provider = MockProvider()
        ctx = InitializeContext(provider=provider, harness_config=get_harness_type("claude-code"))
        await pipeline.execute(ctx)

        assert order == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_records_timings(self):
        async def noop(ctx: InitializeContext) -> None:
            pass

        pipeline = InitializeSandbox(
            [
                InitializeStep(name="fast_step", execute=noop),
            ]
        )

        provider = MockProvider()
        ctx = InitializeContext(provider=provider, harness_config=get_harness_type("claude-code"))
        timings = await pipeline.execute(ctx)

        assert "fast_step" in timings
        assert "_total" in timings
        assert timings["fast_step"] >= 0
        assert timings["_total"] >= 0

    @pytest.mark.asyncio
    async def test_skip_if_respected(self):
        order: list[str] = []

        async def step_a(ctx: InitializeContext) -> None:
            order.append("a")

        async def step_b(ctx: InitializeContext) -> None:
            order.append("b")

        pipeline = InitializeSandbox(
            [
                InitializeStep(name="a", execute=step_a, skip_if=lambda ctx: True),
                InitializeStep(name="b", execute=step_b),
            ]
        )

        provider = MockProvider()
        ctx = InitializeContext(provider=provider, harness_config=get_harness_type("claude-code"))
        await pipeline.execute(ctx)

        assert order == ["b"]
        assert ctx.timings["a"] == 0.0

    @pytest.mark.asyncio
    async def test_error_halts_pipeline(self):
        order: list[str] = []

        async def step_ok(ctx: InitializeContext) -> None:
            order.append("ok")

        async def step_fail(ctx: InitializeContext) -> None:
            raise RuntimeError("boom")

        async def step_after(ctx: InitializeContext) -> None:
            order.append("after")

        pipeline = InitializeSandbox(
            [
                InitializeStep(name="ok", execute=step_ok),
                InitializeStep(name="fail", execute=step_fail),
                InitializeStep(name="after", execute=step_after),
            ]
        )

        provider = MockProvider()
        ctx = InitializeContext(provider=provider, harness_config=get_harness_type("claude-code"))

        with pytest.raises(RuntimeError, match="boom"):
            await pipeline.execute(ctx)

        assert order == ["ok"]

    @pytest.mark.asyncio
    async def test_context_state_propagates_between_steps(self):
        async def step_write(ctx: InitializeContext) -> None:
            ctx.cwd = "/workspace/myrepo"

        async def step_read(ctx: InitializeContext) -> None:
            assert ctx.cwd == "/workspace/myrepo"

        pipeline = InitializeSandbox(
            [
                InitializeStep(name="write", execute=step_write),
                InitializeStep(name="read", execute=step_read),
            ]
        )

        provider = MockProvider()
        ctx = InitializeContext(provider=provider, harness_config=get_harness_type("claude-code"))
        await pipeline.execute(ctx)

    def test_step_names(self):
        async def noop(ctx: InitializeContext) -> None:
            pass

        pipeline = InitializeSandbox(
            [
                InitializeStep(name="a", execute=noop),
                InitializeStep(name="b", execute=noop),
                InitializeStep(name="c", execute=noop),
            ]
        )

        assert pipeline.step_names() == ["a", "b", "c"]

    def test_dry_run_respects_skip_if(self):
        async def noop(ctx: InitializeContext) -> None:
            pass

        pipeline = InitializeSandbox(
            [
                InitializeStep(name="always", execute=noop),
                InitializeStep(name="skipped", execute=noop, skip_if=lambda ctx: True),
                InitializeStep(
                    name="conditional", execute=noop, skip_if=lambda ctx: ctx.workspace is None
                ),
            ]
        )

        provider = MockProvider()
        ctx = InitializeContext(provider=provider, harness_config=get_harness_type("claude-code"))
        result = pipeline.dry_run(ctx)

        assert result == ["always"]


class TestInitializeSandboxFactory:
    def test_default_pipeline_step_names(self):
        pipeline = initialize_sandbox()
        names = pipeline.step_names()
        assert names == [
            "create_sandbox",
            "check_tools",
            "create_workspace_root",
            "inject_env",
            "inject_workspace",
            "attach_mount",
            "run_setup_script",
        ]

    def test_extra_steps_appended(self):
        async def custom(ctx: InitializeContext) -> None:
            pass

        pipeline = initialize_sandbox(extra_steps=[InitializeStep(name="custom_step", execute=custom)])
        names = pipeline.step_names()
        assert names[-1] == "custom_step"

    @pytest.mark.asyncio
    async def test_full_pipeline_with_mock_provider(self):
        """Run the full default pipeline against MockProvider."""
        provider = MockProvider()
        ctx = InitializeContext(
            provider=provider,
            harness_config=get_harness_type("claude-code"),
            env_vars={"TEST": "1"},
        )
        pipeline = initialize_sandbox()
        await pipeline.execute(ctx)

        assert provider._sandbox_id == "mock-sandbox-123"
        assert "/workspace" in provider._dirs
        # Slim init does not build/inject harness manifests
        assert ctx.manifest is None
        assert provider._files == {}

    @pytest.mark.asyncio
    async def test_configure_path_injects_security_files(self):
        """Future configure path still writes settings/hooks via build_and_inject_manifest."""
        from harnessbox.config.pipeline import build_and_inject_manifest

        provider = MockProvider()
        policy = SecurityPolicy(denied_tools=["WebFetch"], deny_network=True)
        ctx = InitializeContext(
            provider=provider,
            harness_config=get_harness_type("claude-code"),
            security_policy=policy,
        )
        await provider.create()
        await provider.make_dir("/workspace")
        await build_and_inject_manifest(ctx)

        assert "/workspace/.claude/settings.json" in provider._files
        assert "/workspace/.claude/hooks/guard_bash.py" in provider._files
        chmod_cmds = [c for c in provider._commands if "chmod" in c]
        assert len(chmod_cmds) == 1

    @pytest.mark.asyncio
    async def test_pipeline_with_setup_script(self):
        """Setup script runs at the end."""
        provider = MockProvider()
        ctx = InitializeContext(
            provider=provider,
            harness_config=get_harness_type("claude-code"),
            setup_script="npm install",
        )
        pipeline = initialize_sandbox()
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

        ctx = InitializeContext(
            provider=provider,
            harness_config=get_harness_type("claude-code"),
            setup_script="npm install",
        )
        pipeline = initialize_sandbox()

        with pytest.raises(RuntimeError, match="Setup script failed"):
            await pipeline.execute(ctx)

    @pytest.mark.asyncio
    async def test_pipeline_skips_workspace_when_none(self):
        """inject_workspace step is skipped when no workspace configured."""
        provider = MockProvider()
        ctx = InitializeContext(
            provider=provider,
            harness_config=get_harness_type("claude-code"),
        )
        pipeline = initialize_sandbox()
        result = pipeline.dry_run(ctx)

        assert "inject_workspace" not in result
        assert "attach_mount" not in result


class TestSandboxDryRun:
    """Test the Sandbox.dry_run() method that wraps pipeline.dry_run()."""

    def test_dry_run_returns_step_names(self):
        from harnessbox.sandbox import Sandbox

        provider = MockProvider()
        sb = Sandbox(client=provider, harness="claude-code")
        steps = sb.dry_run()

        assert "create_sandbox" in steps
        assert "inject_env" in steps
        assert "build_manifest" not in steps
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

    def test_dry_run_excludes_hooks_even_with_policy(self):
        from harnessbox.sandbox import Sandbox

        provider = MockProvider()
        sb = Sandbox(
            client=provider,
            harness="claude-code",
            security_policy=SecurityPolicy(),
        )
        steps = sb.dry_run()

        assert "set_hook_permissions" not in steps
        assert "inject_files" not in steps
