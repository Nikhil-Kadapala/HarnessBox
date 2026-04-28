"""Tests for harnessbox.session — SessionManager + SessionConfig."""

from __future__ import annotations

import pytest

from harnessbox.session import SessionConfig, SessionManager, SessionNotFoundError
from harnessbox.streaming import EventType

from .conftest import MockProvider


@pytest.fixture
def mock_provider() -> MockProvider:
    return MockProvider()


class TestSessionConfig:
    def test_defaults(self) -> None:
        config = SessionConfig()
        assert config.provider == "e2b"
        assert config.harness == "claude-code"
        assert config.timeout == 300
        assert config.skip_permissions is False

    def test_custom_values(self) -> None:
        config = SessionConfig(
            provider="e2b",
            harness="claude-code",
            env_vars={"KEY": "val"},
            skip_permissions=True,
        )
        assert config.env_vars == {"KEY": "val"}
        assert config.skip_permissions is True


class TestSessionManager:
    @pytest.mark.asyncio
    async def test_create_session(self, mock_provider: MockProvider) -> None:
        mgr = SessionManager()
        config = SessionConfig()

        from unittest.mock import AsyncMock, patch

        with patch("harnessbox.session.Sandbox") as MockSandbox:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance.sandbox_id = "sb-1"

            info = await mgr.create_session(config, session_id="test-1")

        assert info.session_id == "test-1"
        assert info.harness == "claude-code"
        assert info.status == "active"

    @pytest.mark.asyncio
    async def test_get_session(self, mock_provider: MockProvider) -> None:
        mgr = SessionManager()
        config = SessionConfig()

        from unittest.mock import AsyncMock, patch

        with patch("harnessbox.session.Sandbox") as MockSandbox:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            await mgr.create_session(config, session_id="s-1")

        info = mgr.get_session("s-1")
        assert info.session_id == "s-1"

    def test_get_session_not_found(self) -> None:
        mgr = SessionManager()
        with pytest.raises(SessionNotFoundError):
            mgr.get_session("nonexistent")

    @pytest.mark.asyncio
    async def test_list_sessions(self) -> None:
        mgr = SessionManager()

        from unittest.mock import AsyncMock, patch

        with patch("harnessbox.session.Sandbox") as MockSandbox:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            await mgr.create_session(SessionConfig(), session_id="s-1")
            await mgr.create_session(SessionConfig(), session_id="s-2")

        sessions = mgr.list_sessions()
        assert len(sessions) == 2
        ids = {s.session_id for s in sessions}
        assert ids == {"s-1", "s-2"}

    @pytest.mark.asyncio
    async def test_destroy_session(self) -> None:
        mgr = SessionManager()

        from unittest.mock import AsyncMock, patch

        with patch("harnessbox.session.Sandbox") as MockSandbox:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance.kill = AsyncMock()
            await mgr.create_session(SessionConfig(), session_id="s-1")

        await mgr.destroy_session("s-1")
        assert len(mgr.list_sessions()) == 0

    @pytest.mark.asyncio
    async def test_destroy_nonexistent_raises(self) -> None:
        mgr = SessionManager()
        with pytest.raises(SessionNotFoundError):
            await mgr.destroy_session("nope")

    @pytest.mark.asyncio
    async def test_shutdown_all(self) -> None:
        mgr = SessionManager()

        from unittest.mock import AsyncMock, patch

        with patch("harnessbox.session.Sandbox") as MockSandbox:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance.kill = AsyncMock()
            await mgr.create_session(SessionConfig(), session_id="s-1")
            await mgr.create_session(SessionConfig(), session_id="s-2")

        await mgr.shutdown_all()
        assert len(mgr.list_sessions()) == 0

    @pytest.mark.asyncio
    async def test_prompt_yields_events(self) -> None:
        mgr = SessionManager()

        from unittest.mock import AsyncMock, patch

        async def mock_events(prompt: str):  # type: ignore[no-untyped-def]
            from harnessbox.streaming import UniversalEvent

            yield UniversalEvent(
                event_id="e-1",
                sequence=1,
                timestamp="2026-01-01T00:00:00Z",
                session_id="s-1",
                event_type=EventType.ITEM_DELTA,
                delta="hello",
            )

        with patch("harnessbox.session.Sandbox") as MockSandbox:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance.run_prompt_events = mock_events
            await mgr.create_session(SessionConfig(), session_id="s-1")

        events = []
        async for event in mgr.prompt("s-1", "test prompt"):
            events.append(event)

        assert len(events) == 1
        assert events[0].delta == "hello"
