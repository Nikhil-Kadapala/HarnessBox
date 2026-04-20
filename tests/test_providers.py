"""Tests for harnessbox.providers and _providers registry."""

from __future__ import annotations

import pytest

from harnessbox.providers import CommandHandle, CommandResult, SandboxProvider

from .conftest import MockProvider


class TestCommandResult:
    def test_construction(self):
        r = CommandResult(exit_code=0, stdout="hello", stderr="")
        assert r.exit_code == 0
        assert r.stdout == "hello"
        assert r.stderr == ""

    def test_nonzero_exit(self):
        r = CommandResult(exit_code=1, stdout="", stderr="error")
        assert r.exit_code == 1
        assert r.stderr == "error"


class TestCommandHandle:
    def test_construction(self):
        h = CommandHandle(pid=42)
        assert h.pid == 42


class TestSandboxProviderProtocol:
    def test_is_runtime_checkable(self):
        assert hasattr(SandboxProvider, "__protocol_attrs__") or hasattr(
            SandboxProvider, "__abstractmethods__"
        )

    def test_mock_provider_satisfies_protocol(self):
        provider = MockProvider()
        assert isinstance(provider, SandboxProvider)


class TestProviderRegistry:
    def test_list_providers(self):
        from harnessbox._providers import list_providers

        providers = list_providers()
        assert "e2b" in providers
        assert "docker" in providers
        assert "daytona" in providers
        assert "ec2" in providers

    def test_unknown_provider_raises_key_error(self):
        from harnessbox._providers import get_provider_class

        with pytest.raises(KeyError, match="Unknown provider"):
            get_provider_class("nonexistent")

    def test_register_custom_provider(self):
        from harnessbox._providers import _PROVIDER_REGISTRY, register_provider

        register_provider("custom", "harnessbox._providers.docker", "DockerProvider")
        assert "custom" in _PROVIDER_REGISTRY
        del _PROVIDER_REGISTRY["custom"]

    def test_docker_stub_raises_not_implemented(self):
        from harnessbox._providers.docker import DockerProvider

        with pytest.raises(NotImplementedError, match="not yet implemented"):
            DockerProvider()

    def test_daytona_stub_raises_not_implemented(self):
        from harnessbox._providers.daytona import DaytonaProvider

        with pytest.raises(NotImplementedError, match="not yet implemented"):
            DaytonaProvider()

    def test_ec2_stub_raises_not_implemented(self):
        from harnessbox._providers.ec2 import EC2Provider

        with pytest.raises(NotImplementedError, match="not yet implemented"):
            EC2Provider()

    def test_get_provider_class_e2b(self):
        from harnessbox._providers import get_provider_class
        from harnessbox._providers.e2b import E2BProvider

        cls = get_provider_class("e2b")
        assert cls is E2BProvider
