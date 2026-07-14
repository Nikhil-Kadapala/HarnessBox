"""Tests for harnessbox.server — HTTP/SSE endpoints."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from harnessbox._server.workspace_manager import WorkspaceManager
from harnessbox.server import create_app


@pytest.fixture
def manager() -> WorkspaceManager:
    return WorkspaceManager()


@pytest.fixture
def client(manager: WorkspaceManager) -> TestClient:
    app = create_app(manager=manager)
    return TestClient(app)


class TestCreateSession:
    def test_create_session(self, client: TestClient) -> None:
        with patch("harnessbox._server.registry.Sandbox") as MockSandbox:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance.sandbox_id = "sb-1"
            instance.event_buffer = MagicMock()
            instance.event_buffer.push = AsyncMock()
            instance._event_buffer = instance.event_buffer

            resp = client.post(
                "/v1/workspaces",
                json={"harness": "claude-code", "session_id": "test-1"},
            )

        assert resp.status_code == 202
        data = resp.json()
        assert data["session_id"] == "test-1"
        assert data["harness"] == "claude-code"
        assert data["runtime_state"] == "starting"

        # Background task completes provisioning (TestClient runs them synchronously)
        get_resp = client.get("/v1/workspaces/test-1")
        assert get_resp.json()["runtime_state"] == "active"


class TestListSessions:
    def test_list_empty(self, client: TestClient) -> None:
        resp = client.get("/v1/workspaces")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_with_sessions(self, client: TestClient) -> None:
        with patch("harnessbox._server.registry.Sandbox") as MockSandbox:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            client.post("/v1/workspaces", json={"session_id": "s-1"})
            client.post("/v1/workspaces", json={"session_id": "s-2"})

        resp = client.get("/v1/workspaces")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2


class TestGetSession:
    def test_get_existing(self, client: TestClient) -> None:
        with patch("harnessbox._server.registry.Sandbox") as MockSandbox:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            client.post("/v1/workspaces", json={"session_id": "s-1"})

        resp = client.get("/v1/workspaces/s-1")
        assert resp.status_code == 200
        assert resp.json()["session_id"] == "s-1"

    def test_get_not_found(self, client: TestClient) -> None:
        resp = client.get("/v1/workspaces/nonexistent")
        assert resp.status_code == 404


class TestDestroySession:
    def test_destroy_existing(self, client: TestClient) -> None:
        with patch("harnessbox._server.registry.Sandbox") as MockSandbox:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance.kill = AsyncMock()
            client.post("/v1/workspaces", json={"session_id": "s-1"})

        resp = client.delete("/v1/workspaces/s-1")
        assert resp.status_code == 204

        resp = client.get("/v1/workspaces/s-1")
        assert resp.status_code == 404

    def test_destroy_not_found(self, client: TestClient) -> None:
        resp = client.delete("/v1/workspaces/nonexistent")
        assert resp.status_code == 404


class TestCredentialStatus:
    def test_returns_probes(self, client: TestClient) -> None:
        resp = client.get("/v1/credentials/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "probes" in data
        assert "timestamp" in data
        assert isinstance(data["probes"], list)
        for probe in data["probes"]:
            assert "name" in probe
            assert "available" in probe
            assert isinstance(probe["available"], bool)
            assert "value" not in probe
            assert "masked_value" not in probe
            assert "location" not in probe


class TestListHarnesses:
    def test_returns_harness_types(self, client: TestClient) -> None:
        resp = client.get("/v1/harnesses")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 3
        names = {h["name"] for h in data}
        assert {"claude-code", "codex", "opencode"}.issubset(names)
        for h in data:
            assert "cli_command" in h
            assert "supports_persistent" in h
            assert "workspace_root" in h


class TestListProviders:
    def test_returns_providers(self, client: TestClient) -> None:
        resp = client.get("/v1/providers")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        names = {p["name"] for p in data}
        assert "e2b" in names


class TestListGuards:
    def test_returns_guard_sets(self, client: TestClient) -> None:
        resp = client.get("/v1/guards")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 10
        names = {g["name"] for g in data}
        assert "aws" in names
        assert "llm_providers" in names
        for g in data:
            assert "bash_deny_count" in g
            assert "read_deny_count" in g


class TestCORS:
    def test_cors_headers_present(self, client: TestClient) -> None:
        resp = client.options(
            "/v1/workspaces",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"


class TestCreateSessionExpanded:
    def test_with_security_policy(self, client: TestClient) -> None:
        with patch("harnessbox._server.registry.Sandbox") as MockSandbox:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance.sandbox_id = "sb-1"
            instance.event_buffer = MagicMock()
            instance.event_buffer.push = AsyncMock()
            instance._event_buffer = instance.event_buffer

            resp = client.post(
                "/v1/workspaces",
                json={
                    "session_id": "sp-1",
                    "security_policy": {
                        "denied_tools": ["WebFetch"],
                        "deny_network": True,
                        "credential_guards": ["aws", "gcp"],
                    },
                },
            )
        assert resp.status_code == 202

    def test_with_workspace(self, client: TestClient) -> None:
        with patch("harnessbox._server.registry.Sandbox") as MockSandbox:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance.sandbox_id = "sb-1"
            instance.event_buffer = MagicMock()
            instance.event_buffer.push = AsyncMock()
            instance._event_buffer = instance.event_buffer

            resp = client.post(
                "/v1/workspaces",
                json={
                    "session_id": "ws-1",
                    "workspace": {
                        "remote": "https://github.com/test/repo.git",
                        "branch": "main",
                    },
                },
            )
        assert resp.status_code == 202

    def test_invalid_security_policy(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/workspaces",
            json={
                "security_policy": {
                    "denied_tools": "not-a-list",
                },
            },
        )
        assert resp.status_code == 422

    def test_invalid_workspace_missing_remote(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/workspaces",
            json={
                "workspace": {
                    "branch": "main",
                },
            },
        )
        assert resp.status_code == 422


class TestPromptSession:
    def test_prompt_not_found(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/workspaces/nonexistent/prompt",
            json={"prompt": "hello", "harness": "claude-code"},
        )
        assert resp.status_code == 404

    def test_prompt_missing_prompt(self, client: TestClient) -> None:
        with patch("harnessbox._server.registry.Sandbox") as MockSandbox:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            client.post("/v1/workspaces", json={"session_id": "s-1"})

        resp = client.post("/v1/workspaces/s-1/prompt", json={})
        assert resp.status_code == 422


class TestPauseSession:
    def test_pause_active_session(self, client: TestClient) -> None:
        with patch("harnessbox._server.registry.Sandbox") as MockSandbox:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance.pause = AsyncMock(return_value="sb-paused-1")
            instance.create_snapshot = AsyncMock(return_value="snap-1")
            client.post("/v1/workspaces", json={"session_id": "s-1"})

        resp = client.post("/v1/workspaces/s-1/pause")
        assert resp.status_code == 200
        assert resp.json()["runtime_state"] == "paused"
        instance.create_snapshot.assert_called_once()
        instance.pause.assert_called_once()

    def test_pause_non_active_returns_409(
        self, client: TestClient, manager: WorkspaceManager
    ) -> None:
        with patch("harnessbox._server.registry.Sandbox") as MockSandbox:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance.pause = AsyncMock(return_value="sb-1")
            instance.create_snapshot = AsyncMock(return_value="snap-1")
            client.post("/v1/workspaces", json={"session_id": "s-1"})

        # Pause first
        client.post("/v1/workspaces/s-1/pause")
        # Pause again should fail
        resp = client.post("/v1/workspaces/s-1/pause")
        assert resp.status_code == 409

    def test_pause_not_found(self, client: TestClient) -> None:
        resp = client.post("/v1/workspaces/nonexistent/pause")
        assert resp.status_code == 404


class TestResumeSession:
    def test_resume_paused_session(self, client: TestClient) -> None:
        with patch("harnessbox._server.registry.Sandbox") as MockSandbox:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance.pause = AsyncMock(return_value="sb-paused-1")
            instance.create_snapshot = AsyncMock(return_value="snap-1")
            instance.resume = AsyncMock()
            client.post("/v1/workspaces", json={"session_id": "s-1"})

        client.post("/v1/workspaces/s-1/pause")
        resp = client.post("/v1/workspaces/s-1/resume")
        assert resp.status_code == 200
        assert resp.json()["runtime_state"] == "active"

    def test_resume_non_paused_returns_409(self, client: TestClient) -> None:
        with patch("harnessbox._server.registry.Sandbox") as MockSandbox:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            client.post("/v1/workspaces", json={"session_id": "s-1"})

        resp = client.post("/v1/workspaces/s-1/resume")
        assert resp.status_code == 409

    def test_resume_not_found(self, client: TestClient) -> None:
        resp = client.post("/v1/workspaces/nonexistent/resume")
        assert resp.status_code == 404


class TestStopSession:
    def test_stop_session(self, client: TestClient) -> None:
        with patch("harnessbox._server.registry.Sandbox") as MockSandbox:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance.kill = AsyncMock()
            client.post("/v1/workspaces", json={"session_id": "s-1"})

        resp = client.post("/v1/workspaces/s-1/stop")
        assert resp.status_code == 204

    def test_stop_not_found(self, client: TestClient) -> None:
        resp = client.post("/v1/workspaces/nonexistent/stop")
        assert resp.status_code == 404

    def test_stop_session_still_provisioning(
        self, client: TestClient, manager: WorkspaceManager
    ) -> None:
        """Stopping a session with no live sandbox yet (sandbox_conn=None) must not 500."""
        from harnessbox._server.registry import WorkspaceConfig

        manager.register_workspace(WorkspaceConfig(), workspace_id="s-starting")

        resp = client.post("/v1/workspaces/s-starting/stop")
        assert resp.status_code == 204

        get_resp = client.get("/v1/workspaces/s-starting")
        assert get_resp.json()["runtime_state"] == "dead"


class TestRetrySession:
    def _create_errored_session(self, client: TestClient, session_id: str = "s-err") -> None:
        with patch("harnessbox._server.registry.Sandbox") as MockSandbox:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock(side_effect=RuntimeError("boom"))
            client.post("/v1/workspaces", json={"session_id": session_id})

    def test_retry_reprovisions_errored_session(self, client: TestClient) -> None:
        self._create_errored_session(client)
        assert client.get("/v1/workspaces/s-err").json()["runtime_state"] == "error"

        with patch("harnessbox._server.registry.Sandbox") as MockSandbox:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance.sandbox_id = "sb-retry-1"
            instance.event_buffer = MagicMock()
            instance.event_buffer.push = AsyncMock()
            instance._event_buffer = instance.event_buffer
            resp = client.post("/v1/workspaces/s-err/retry")

        assert resp.status_code == 202

        data = client.get("/v1/workspaces/s-err").json()
        assert data["runtime_state"] == "active"
        assert data["error_message"] is None

    def test_retry_non_error_session_returns_409(self, client: TestClient) -> None:
        with patch("harnessbox._server.registry.Sandbox") as MockSandbox:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            client.post("/v1/workspaces", json={"session_id": "s-1"})

        resp = client.post("/v1/workspaces/s-1/retry")
        assert resp.status_code == 409

    def test_retry_not_found_returns_404(self, client: TestClient) -> None:
        resp = client.post("/v1/workspaces/nonexistent/retry")
        assert resp.status_code == 404


class TestTransitionSession:
    def _create_active_session(self, client: TestClient, session_id: str = "s-1") -> None:
        with patch("harnessbox._server.registry.Sandbox") as MockSandbox:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            client.post("/v1/workspaces", json={"session_id": session_id})

    def test_valid_runtime_transition(self, client: TestClient) -> None:
        self._create_active_session(client)
        resp = client.post(
            "/v1/workspaces/s-1/transition",
            json={"dimension": "runtime", "target_state": "paused"},
        )
        assert resp.status_code == 200
        assert resp.json()["runtime_state"] == "paused"

    def test_invalid_transition_returns_409(self, client: TestClient) -> None:
        self._create_active_session(client)
        resp = client.post(
            "/v1/workspaces/s-1/transition",
            json={"dimension": "runtime", "target_state": "starting"},
        )
        assert resp.status_code == 409

    def test_workflow_dimension_returns_400(self, client: TestClient) -> None:
        self._create_active_session(client)
        resp = client.post(
            "/v1/workspaces/s-1/transition",
            json={"dimension": "workflow", "target_state": "in_review"},
        )
        assert resp.status_code == 400

    def test_unknown_state_returns_400(self, client: TestClient) -> None:
        self._create_active_session(client)
        resp = client.post(
            "/v1/workspaces/s-1/transition",
            json={"dimension": "runtime", "target_state": "imaginary"},
        )
        assert resp.status_code == 400

    def test_unknown_session_returns_404(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/workspaces/nonexistent/transition",
            json={"dimension": "runtime", "target_state": "paused"},
        )
        assert resp.status_code == 404


class TestRemovedEndpointsGone:
    """Phase 0 cut: PR, rename, and stats endpoints no longer exist."""

    def test_pr_endpoints_removed(self, client: TestClient) -> None:
        assert client.post("/v1/workspaces/s-1/pr", json={"title": "t"}).status_code == 404
        assert client.post("/v1/workspaces/s-1/pr/refresh").status_code == 404

    def test_rename_endpoint_removed(self, client: TestClient) -> None:
        assert client.post("/v1/workspaces/s-1/rename", json={"name": "x"}).status_code == 404

    def test_stats_endpoint_removed(self, client: TestClient) -> None:
        assert client.get("/v1/workspaces/s-1/stats").status_code == 404


class TestWorkspaceEndpoints:
    """Test workspace name generation and detection endpoints."""

    def test_generate_workspace_name(self, client: TestClient) -> None:
        """GET /v1/workspace/name should return a name."""
        resp = client.get("/v1/workspace/name")
        assert resp.status_code == 200
        data = resp.json()
        assert "name" in data
        assert isinstance(data["name"], str)
        assert len(data["name"]) > 0

    def test_ssh_to_https_conversion(self, client: TestClient, tmp_path) -> None:
        """Detect should convert SSH URLs to HTTPS."""
        import subprocess

        repo_path = tmp_path / "ssh-repo"
        repo_path.mkdir()
        subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "git@github.com:user/repo.git"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )

        resp = client.get(f"/v1/workspace/detect?path={repo_path}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["remote"] == "https://github.com/user/repo.git"
        assert "git@" not in data["remote"]

    def test_detect_workspace_valid_repo(self, client: TestClient, tmp_path) -> None:
        """GET /v1/workspace/detect should detect repo info."""
        import subprocess

        repo_path = tmp_path / "test-repo"
        repo_path.mkdir()
        subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/test/repo.git"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )

        resp = client.get(f"/v1/workspace/detect?path={repo_path}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["remote"] == "https://github.com/test/repo.git"
        assert "default_branch" in data
        assert data["name"] == "test-repo"

    def test_detect_workspace_not_a_repo(self, client: TestClient, tmp_path) -> None:
        """GET /v1/workspace/detect should return 400 for non-git paths."""
        non_repo = tmp_path / "not-a-repo"
        non_repo.mkdir()

        resp = client.get(f"/v1/workspace/detect?path={non_repo}")
        assert resp.status_code == 400
        assert "Not a git repository" in resp.json()["detail"]

    def test_detect_workspace_no_remote(self, client: TestClient, tmp_path) -> None:
        """GET /v1/workspace/detect should return 400 when no remote exists."""
        import subprocess

        repo_path = tmp_path / "no-remote-repo"
        repo_path.mkdir()
        subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)

        resp = client.get(f"/v1/workspace/detect?path={repo_path}")
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "Failed to read remote URL" in detail or "No remote.origin.url found" in detail


class TestServerTimeoutFields:
    def test_create_workspace_with_timeouts(self) -> None:
        app = create_app(manager=WorkspaceManager())
        client = TestClient(app)

        with patch("harnessbox._server.registry.Sandbox") as MockSandbox:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance.sandbox_id = "sb-1"
            instance.event_buffer = MagicMock()
            instance.event_buffer.push = AsyncMock()
            instance._event_buffer = instance.event_buffer

            resp = client.post(
                "/v1/workspaces",
                json={
                    "session_id": "t-1",
                    "sandbox_timeout": 3600,
                    "session_timeout": 1800,
                },
            )
        assert resp.status_code == 202

    def test_session_timeout_clamped_to_sandbox_timeout(self) -> None:
        app = create_app(manager=WorkspaceManager())
        client = TestClient(app)

        with patch("harnessbox._server.registry.Sandbox") as MockSandbox:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance.sandbox_id = "sb-1"
            instance.event_buffer = MagicMock()
            instance.event_buffer.push = AsyncMock()
            instance._event_buffer = instance.event_buffer

            resp = client.post(
                "/v1/workspaces",
                json={
                    "session_id": "t-2",
                    "sandbox_timeout": 300,
                    "session_timeout": 600,
                },
            )
        assert resp.status_code == 202


class TestExportEventsJsonl:
    """GET /v1/workspaces/{id}/events.jsonl — full durable event log export."""

    async def _client_with_storage(self) -> TestClient:
        from harnessbox._server._storage.memory import MemoryBackend

        storage = MemoryBackend()
        await storage.initialize()
        mgr = await WorkspaceManager.create(storage=storage)
        return TestClient(create_app(manager=mgr))

    @pytest.mark.asyncio
    async def test_export_returns_ndjson_of_persisted_events(self) -> None:
        from dataclasses import replace

        client = await self._client_with_storage()

        # Real EventBuffer.push() assigns a fresh monotonic sequence (>= 1)
        # per call; a bare identity echo would leave every event at
        # sequence=0, which get_history()'s default after_sequence=0 filter
        # excludes (sequence > after_sequence, not >=).
        next_seq = [0]

        async def _assign_sequence(event):
            next_seq[0] += 1
            return replace(event, sequence=next_seq[0])

        with patch("harnessbox._server.registry.Sandbox") as MockSandbox:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            instance.sandbox_id = "sb-export"
            instance.event_buffer = MagicMock()
            instance.event_buffer.push = AsyncMock(side_effect=_assign_sequence)
            instance._event_buffer = instance.event_buffer
            resp = client.post("/v1/workspaces", json={"session_id": "s-export"})
            assert resp.status_code == 202

        resp = client.get("/v1/workspaces/s-export/events.jsonl")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/x-ndjson")
        assert "attachment" in resp.headers["content-disposition"]
        assert "s-export-events.jsonl" in resp.headers["content-disposition"]

        lines = [line for line in resp.text.strip().split("\n") if line]
        assert len(lines) >= 1
        events = [json.loads(line) for line in lines]
        assert any(e["type"] == "runtime.state" for e in events)

    @pytest.mark.asyncio
    async def test_export_unknown_session_returns_404(self) -> None:
        client = await self._client_with_storage()
        resp = client.get("/v1/workspaces/nonexistent/events.jsonl")
        assert resp.status_code == 404

    def test_export_without_storage_returns_400(self, client: TestClient) -> None:
        with patch("harnessbox._server.registry.Sandbox") as MockSandbox:
            instance = MockSandbox.return_value
            instance.setup = AsyncMock()
            client.post("/v1/workspaces", json={"session_id": "s-1"})

        resp = client.get("/v1/workspaces/s-1/events.jsonl")
        assert resp.status_code == 400
