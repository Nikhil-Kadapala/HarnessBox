"""Tests for harnessbox.server — HTTP/SSE endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from harnessbox.server import create_app
from harnessbox.session import SessionManager


@pytest.fixture
def manager() -> SessionManager:
    return SessionManager()


@pytest.fixture
def client(manager: SessionManager) -> TestClient:
    app = create_app(manager=manager)
    return TestClient(app)


class TestCreateSession:
    def test_create_session(self, client: TestClient) -> None:
        with patch("harnessbox.session.Sandbox") as MockSandbox:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance.sandbox_id = "sb-1"

            resp = client.post(
                "/v1/sessions",
                json={"harness": "claude-code", "session_id": "test-1"},
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["session_id"] == "test-1"
        assert data["harness"] == "claude-code"
        assert data["status"] == "active"


class TestListSessions:
    def test_list_empty(self, client: TestClient) -> None:
        resp = client.get("/v1/sessions")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_with_sessions(self, client: TestClient) -> None:
        with patch("harnessbox.session.Sandbox") as MockSandbox:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            client.post("/v1/sessions", json={"session_id": "s-1"})
            client.post("/v1/sessions", json={"session_id": "s-2"})

        resp = client.get("/v1/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2


class TestGetSession:
    def test_get_existing(self, client: TestClient) -> None:
        with patch("harnessbox.session.Sandbox") as MockSandbox:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            client.post("/v1/sessions", json={"session_id": "s-1"})

        resp = client.get("/v1/sessions/s-1")
        assert resp.status_code == 200
        assert resp.json()["session_id"] == "s-1"

    def test_get_not_found(self, client: TestClient) -> None:
        resp = client.get("/v1/sessions/nonexistent")
        assert resp.status_code == 404


class TestDestroySession:
    def test_destroy_existing(self, client: TestClient) -> None:
        with patch("harnessbox.session.Sandbox") as MockSandbox:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance.kill = AsyncMock()
            client.post("/v1/sessions", json={"session_id": "s-1"})

        resp = client.delete("/v1/sessions/s-1")
        assert resp.status_code == 204

        resp = client.get("/v1/sessions/s-1")
        assert resp.status_code == 404

    def test_destroy_not_found(self, client: TestClient) -> None:
        resp = client.delete("/v1/sessions/nonexistent")
        assert resp.status_code == 404


class TestPromptSession:
    def test_prompt_not_found(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/sessions/nonexistent/prompt",
            json={"prompt": "hello"},
        )
        assert resp.status_code == 404

    def test_prompt_missing_prompt(self, client: TestClient) -> None:
        with patch("harnessbox.session.Sandbox") as MockSandbox:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            client.post("/v1/sessions", json={"session_id": "s-1"})

        resp = client.post("/v1/sessions/s-1/prompt", json={})
        assert resp.status_code == 422
