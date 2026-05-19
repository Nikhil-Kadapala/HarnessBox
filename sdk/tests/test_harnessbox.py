"""Tests for HarnessBox — the public API wrapper."""

import pytest

from harnessbox.harnessbox import HarnessBox, HarnessBoxSecrets


class TestHarnessBoxInit:
    def test_minimal_construction(self):
        hb = HarnessBox(provider="e2b")
        assert hb._provider == "e2b"
        assert hb._harness == "claude-code"
        assert hb._sandbox is None
        assert hb.is_self_hosted is True

    def test_with_platform_api_key(self):
        hb = HarnessBox(provider="e2b", api_key="hb_live_abc123")
        assert hb.is_self_hosted is False

    def test_self_hosted_explicit_key(self):
        hb = HarnessBox(provider="e2b", api_key="hb_self_hosted")
        assert hb.is_self_hosted is True

    def test_secrets_from_dict(self):
        hb = HarnessBox(
            provider="e2b",
            secrets={
                "provider_api_key": "e2b_key_123",
                "harness_secrets": {"ANTHROPIC_API_KEY": "sk-ant-123"},
            },
        )
        assert hb._secrets.provider_api_key == "e2b_key_123"
        assert hb._secrets.harness_secrets == {"ANTHROPIC_API_KEY": "sk-ant-123"}

    def test_secrets_from_dataclass(self):
        s = HarnessBoxSecrets(
            provider_api_key="e2b_key_456",
            harness_secrets={"GITHUB_TOKEN": "ghp_abc"},
        )
        hb = HarnessBox(provider="e2b", secrets=s)
        assert hb._secrets.provider_api_key == "e2b_key_456"
        assert hb._secrets.harness_secrets == {"GITHUB_TOKEN": "ghp_abc"}

    def test_secrets_none_defaults(self):
        hb = HarnessBox(provider="e2b")
        assert hb._secrets.provider_api_key is None
        assert hb._secrets.harness_secrets is None

    def test_env_vars_preserved(self):
        hb = HarnessBox(provider="e2b", env_vars={"MY_VAR": "hello"})
        assert hb._env_vars == {"MY_VAR": "hello"}

    def test_sandbox_id_none_before_create(self):
        hb = HarnessBox(provider="e2b")
        assert hb.sandbox_id is None

    def test_accepts_provider_instance(self, mock_provider):
        hb = HarnessBox(provider=mock_provider)
        assert hb._provider is mock_provider


class TestHarnessBoxLifecycle:
    async def test_create_provisions_sandbox(self, mock_provider):
        hb = HarnessBox(provider=mock_provider)
        sandbox_id = await hb.create()
        assert sandbox_id == "mock-sandbox-123"
        assert hb.sandbox_id == "mock-sandbox-123"
        assert hb._sandbox is not None

    async def test_create_merges_harness_secrets_into_env(self, mock_provider):
        hb = HarnessBox(
            provider=mock_provider,
            env_vars={"EXISTING": "yes"},
            secrets={
                "provider_api_key": None,
                "harness_secrets": {"ANTHROPIC_API_KEY": "sk-test"},
            },
        )
        await hb.create()
        assert mock_provider._env_vars.get("EXISTING") == "yes"
        assert mock_provider._env_vars.get("ANTHROPIC_API_KEY") == "sk-test"

    async def test_require_sandbox_raises_before_create(self):
        hb = HarnessBox(provider="e2b")
        with pytest.raises(RuntimeError, match="not created"):
            hb._require_sandbox()

    async def test_double_create_raises(self, mock_provider):
        hb = HarnessBox(provider=mock_provider)
        await hb.create()
        with pytest.raises(RuntimeError, match="already created"):
            await hb.create()

    async def test_kill_clears_sandbox(self, mock_provider):
        hb = HarnessBox(provider=mock_provider)
        await hb.create()
        await hb.kill()
        assert hb._sandbox is None
        assert hb.sandbox_id is None

    async def test_kill_idempotent_when_no_sandbox(self):
        hb = HarnessBox(provider="e2b")
        await hb.kill()

    async def test_run_command_delegates(self, mock_provider):
        hb = HarnessBox(provider=mock_provider)
        await hb.create()
        result = await hb.run_command("echo hello")
        assert result.exit_code == 0
        assert "echo hello" in mock_provider._commands

    async def test_write_and_read_file(self, mock_provider):
        hb = HarnessBox(provider=mock_provider)
        await hb.create()
        await hb.write_file("/workspace/test.txt", "content")
        content = await hb.read_file("/workspace/test.txt")
        assert content == "content"

    async def test_write_files_delegates(self, mock_provider):
        hb = HarnessBox(provider=mock_provider)
        await hb.create()
        await hb.write_files({"/workspace/a.txt": "aaa", "/workspace/b.txt": "bbb"})
        assert mock_provider._files["/workspace/a.txt"] == "aaa"
        assert mock_provider._files["/workspace/b.txt"] == "bbb"

    async def test_send_message_raises_without_create(self):
        hb = HarnessBox(provider="e2b")
        with pytest.raises(RuntimeError, match="not created"):
            async for _ in hb.send_message("hello"):
                pass

    async def test_context_manager(self, mock_provider):
        async with HarnessBox(provider=mock_provider) as hb:
            assert hb.sandbox_id == "mock-sandbox-123"
        assert hb._sandbox is None
