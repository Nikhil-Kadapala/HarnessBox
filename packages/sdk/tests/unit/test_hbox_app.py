"""Unit tests for hbox REPL slash routing, bare text, and UI helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from typing import Any, AsyncIterator

import pytest

from harnessbox.client import WorkspaceInfo
from harnessbox.hbox.app import (
    ReplState,
    _cmd_model,
    _cmd_project,
    _dispatch,
    _is_github_remote,
    _resolve_git_auth,
    main,
)
from harnessbox.hbox.server_manager import ServerInfo, ServerManager
from harnessbox.hbox.ui import CreateProgress, format_turn_event, model_not_applied_warning
from harnessbox.streaming import EventType, ItemKind, UniversalEvent


@dataclass
class _FakeClient:
    harnesses: list[dict[str, Any]] = field(
        default_factory=lambda: [{"name": "claude-code"}, {"name": "codex"}]
    )
    workspace: WorkspaceInfo | None = None
    create_calls: list[dict[str, Any]] = field(default_factory=list)
    pause_calls: list[str] = field(default_factory=list)
    resume_calls: list[str] = field(default_factory=list)
    prompt_calls: list[tuple[str, str, str]] = field(default_factory=list)
    prompt_events: list[UniversalEvent] = field(default_factory=list)

    async def list_harnesses(self) -> list[dict[str, Any]]:
        return self.harnesses

    async def get_workspace(self, workspace_id: str) -> WorkspaceInfo:
        assert self.workspace is not None
        return self.workspace

    async def create_workspace(self, **kwargs: Any) -> WorkspaceInfo:
        self.create_calls.append(kwargs)
        on_state = kwargs.get("on_state")
        if on_state:
            on_state("starting")
            on_state("active")
        self.workspace = WorkspaceInfo(
            workspace_id="ws-1",
            harness=kwargs.get("harness", "claude-code"),
            state="active",
            created_at="t0",
            remote=kwargs.get("remote"),
            branch=kwargs.get("branch"),
        )
        return self.workspace

    async def pause(self, workspace_id: str) -> WorkspaceInfo:
        self.pause_calls.append(workspace_id)
        assert self.workspace is not None
        self.workspace = WorkspaceInfo(
            workspace_id=workspace_id,
            harness=self.workspace.harness,
            state="paused",
            created_at=self.workspace.created_at,
        )
        return self.workspace

    async def resume(self, workspace_id: str) -> WorkspaceInfo:
        self.resume_calls.append(workspace_id)
        assert self.workspace is not None
        self.workspace = WorkspaceInfo(
            workspace_id=workspace_id,
            harness=self.workspace.harness,
            state="active",
            created_at=self.workspace.created_at,
        )
        return self.workspace

    async def prompt(
        self, workspace_id: str, text: str, harness: str = "claude-code"
    ) -> AsyncIterator[UniversalEvent]:
        self.prompt_calls.append((workspace_id, text, harness))
        for event in self.prompt_events:
            yield event

    async def close(self) -> None:
        return None


class _Mgr(ServerManager):
    def ensure(self) -> ServerInfo:
        return ServerInfo(
            host="127.0.0.1",
            port=8000,
            pid=42,
            started_at="t0",
            spawned=True,
        )

    def stop(self) -> bool:
        return True


def test_create_progress_maps_states() -> None:
    lines: list[str] = []
    progress = CreateProgress(harness="claude-code", print_fn=lines.append)
    progress.registered("ws-9")
    progress.on_state("starting")
    progress.on_state("starting")  # dedupe
    progress.on_state("active")
    progress.resuming()
    assert lines == [
        "    · registered  ws-9",
        "    · provisioning",
        "    · active  claude-code",
        "    · resuming…",
    ]


def test_format_turn_event_delta_and_tool() -> None:
    delta = UniversalEvent(
        event_id="1",
        sequence=1,
        timestamp="t",
        session_id="s",
        event_type=EventType.ITEM_DELTA,
        delta="hi",
    )
    assert format_turn_event(delta) == "hi"

    tool = UniversalEvent(
        event_id="2",
        sequence=2,
        timestamp="t",
        session_id="s",
        event_type=EventType.ITEM_DELTA,
        item_kind=ItemKind.TOOL_CALL if hasattr(ItemKind, "TOOL_CALL") else None,
        content=(),
        tool_kind=None,
    )
    # no delta / no tool content → skip
    assert format_turn_event(tool) is None


def test_format_turn_event_surfaces_turn_ended_error() -> None:
    ended = UniversalEvent(
        event_id="3",
        sequence=3,
        timestamp="t",
        session_id="s",
        event_type=EventType.TURN_ENDED,
        error_message="Not logged in · Please run /login",
    )
    assert format_turn_event(ended) == "\n[error] Not logged in · Please run /login\n"


def test_model_warning_present() -> None:
    assert "not applied" in model_not_applied_warning()


def test_is_github_remote() -> None:
    assert _is_github_remote("https://github.com/org/repo")
    assert _is_github_remote("git@github.com:org/repo.git")
    assert not _is_github_remote("https://gitlab.com/org/repo")


def test_resolve_git_auth_prefers_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setattr("harnessbox.hbox.app.shutil.which", lambda _: None)
    state = ReplState(home=tmp_path, base_url="http://127.0.0.1:8000")
    mode, token = _resolve_git_auth(state, False, StringIO(), StringIO(), StringIO())
    assert mode == "gh"
    assert token is None


def test_resolve_git_auth_stores_pat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr("harnessbox.hbox.app.shutil.which", lambda _: None)
    state = ReplState(home=tmp_path, base_url="http://127.0.0.1:8000")
    mode, token = _resolve_git_auth(state, True, StringIO(), StringIO(), StringIO("ghp_test\n"))
    assert mode == "token"
    assert token == "ghp_test"
    cred = json.loads((tmp_path / "credentials.json").read_text(encoding="utf-8"))
    assert cred["github_token"] == "ghp_test"
    assert (tmp_path / "credentials.json").stat().st_mode & 0o777 == 0o600


def test_cmd_model_sets_local_and_warns(tmp_path: Path) -> None:
    state = ReplState(home=tmp_path, base_url="http://x", project_name="p")
    out = StringIO()
    _cmd_model(["claude-sonnet-4-6"], state=state, out=out)
    assert state.model == "claude-sonnet-4-6"
    assert "not applied" in out.getvalue()


def test_cmd_project_create(tmp_path: Path) -> None:
    state = ReplState(home=tmp_path, base_url="http://x")
    out = StringIO()
    _cmd_project(["create", "demo"], state=state, out=out, err=StringIO())
    assert state.project_name == "demo"
    assert (tmp_path / "projects" / "demo.toml").is_file()


@pytest.mark.asyncio
async def test_slash_harness_list_and_set(tmp_path: Path) -> None:
    state = ReplState(home=tmp_path, base_url="http://x")
    client = _FakeClient()
    out = StringIO()
    await _dispatch(
        "/harness",
        state=state,
        client=client,  # type: ignore[arg-type]
        mgr=_Mgr(home=tmp_path),
        out=out,
        err=StringIO(),
        stdin=StringIO(),
    )
    assert "claude-code" in out.getvalue()

    out2 = StringIO()
    await _dispatch(
        "/harness codex",
        state=state,
        client=client,  # type: ignore[arg-type]
        mgr=_Mgr(home=tmp_path),
        out=out2,
        err=StringIO(),
        stdin=StringIO(),
    )
    assert state.harness == "codex"


@pytest.mark.asyncio
async def test_pause_resume_and_bare_text_auto_resume(tmp_path: Path) -> None:
    state = ReplState(
        home=tmp_path,
        base_url="http://x",
        workspace_id="ws-1",
        runtime_state="paused",
        harness="claude-code",
    )
    client = _FakeClient(
        workspace=WorkspaceInfo(
            workspace_id="ws-1",
            harness="claude-code",
            state="paused",
            created_at="t0",
        ),
        prompt_events=[
            UniversalEvent(
                event_id="1",
                sequence=1,
                timestamp="t",
                session_id="ws-1",
                event_type=EventType.ITEM_DELTA,
                delta="ok",
            )
        ],
    )
    out = StringIO()
    await _dispatch(
        "continue",
        state=state,
        client=client,  # type: ignore[arg-type]
        mgr=_Mgr(home=tmp_path),
        out=out,
        err=StringIO(),
        stdin=StringIO(),
    )
    assert client.resume_calls == ["ws-1"]
    assert client.prompt_calls == [("ws-1", "continue", "claude-code")]
    assert "resuming" in out.getvalue()
    assert "ok" in out.getvalue()


@pytest.mark.asyncio
async def test_add_repo_eager_create_non_github(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr("harnessbox.hbox.app.shutil.which", lambda _: None)
    state = ReplState(home=tmp_path, base_url="http://x")
    client = _FakeClient()
    out = StringIO()
    await _dispatch(
        "/add-repo https://gitlab.com/org/app.git --branch develop",
        state=state,
        client=client,  # type: ignore[arg-type]
        mgr=_Mgr(home=tmp_path),
        out=out,
        err=StringIO(),
        stdin=StringIO(),
    )
    assert state.workspace_id == "ws-1"
    assert state.branch == "develop"
    assert client.create_calls[0]["remote"] == "https://gitlab.com/org/app.git"
    assert client.create_calls[0]["branch"] == "develop"
    assert "active" in out.getvalue() or "ready" in out.getvalue()


@pytest.mark.asyncio
async def test_lazy_bare_text_creates_workspace(tmp_path: Path) -> None:
    state = ReplState(home=tmp_path, base_url="http://x", harness="claude-code")
    client = _FakeClient(
        prompt_events=[
            UniversalEvent(
                event_id="1",
                sequence=1,
                timestamp="t",
                session_id="ws-1",
                event_type=EventType.ITEM_DELTA,
                delta="hello",
            )
        ]
    )
    out = StringIO()
    await _dispatch(
        "hi there",
        state=state,
        client=client,  # type: ignore[arg-type]
        mgr=_Mgr(home=tmp_path),
        out=out,
        err=StringIO(),
        stdin=StringIO(),
    )
    assert state.workspace_id == "ws-1"
    assert client.create_calls
    assert client.prompt_calls[0][1] == "hi there"
    assert "hello" in out.getvalue()


def test_app_exit_stops_server(tmp_path: Path) -> None:
    stopped: list[bool] = []

    class Mgr(_Mgr):
        def stop(self) -> bool:
            stopped.append(True)
            return True

    stdin = StringIO("/exit\n")
    with pytest.raises(SystemExit) as exc:
        main(
            manager=Mgr(home=tmp_path),
            client=_FakeClient(),  # type: ignore[arg-type]
            stdin=stdin,
            stdout=StringIO(),
            stderr=StringIO(),
            home=tmp_path,
        )
    assert exc.value.code == 0
    assert stopped == [True]


@pytest.mark.asyncio
async def test_add_repo_github_sends_git_auth_gh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "env-token")
    monkeypatch.setattr("harnessbox.hbox.app.shutil.which", lambda _: None)
    state = ReplState(home=tmp_path, base_url="http://x", git_auth_mode="gh")
    client = _FakeClient()
    out = StringIO()
    await _dispatch(
        "/add-repo https://github.com/org/app.git",
        state=state,
        client=client,  # type: ignore[arg-type]
        mgr=_Mgr(home=tmp_path),
        out=out,
        err=StringIO(),
        stdin=StringIO(),
    )
    assert client.create_calls[0].get("git_auth") == "gh"
    assert client.create_calls[0].get("git_token") is None

    state = ReplState(
        home=tmp_path,
        base_url="http://127.0.0.1:8000",
        workspace_id="ws-1",
        harness="claude-code",
        model="claude-sonnet-4-6",
        runtime_state="active",
    )
    client = _FakeClient(
        workspace=WorkspaceInfo(
            workspace_id="ws-1",
            harness="claude-code",
            state="active",
            created_at="t0",
        )
    )
    out = StringIO()
    await _dispatch(
        "/status",
        state=state,
        client=client,  # type: ignore[arg-type]
        mgr=_Mgr(home=tmp_path),
        out=out,
        err=StringIO(),
        stdin=StringIO(),
    )
    text = out.getvalue()
    assert "claude-sonnet-4-6" in text
    assert "not applied" in text
