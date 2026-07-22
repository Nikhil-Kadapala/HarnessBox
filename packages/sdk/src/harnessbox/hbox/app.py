"""``hbox`` interactive CLI entry point.

REPL, slash handlers, and local config live here (thin layout — D1).
Server probe/spawn is in ``server_manager``; rich UI helpers are in ``ui``.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TextIO
from urllib.parse import urlparse

from harnessbox.client import HarnessBoxClient, WorkspaceCreationError, WorkspaceInfo
from harnessbox.hbox.server_manager import ServerManager, ServerManagerError, default_home
from harnessbox.hbox.ui import CreateProgress, format_turn_event, model_not_applied_warning
from harnessbox.lifecycle import RuntimeState

_SLASH_COMMANDS = (
    "/project",
    "/harness",
    "/model",
    "/add-repo",
    "/git-auth",
    "/pause",
    "/resume",
    "/status",
    "/exit",
)

# Local-only model catalog (D2). Not sent to the server until configure exists.
_MODELS_BY_HARNESS: dict[str, tuple[str, ...]] = {
    "claude-code": (
        "claude-sonnet-4-6",
        "claude-opus-4",
        "claude-haiku-4-5",
    ),
    "codex": ("gpt-5", "o3", "o4-mini"),
    "opencode": ("claude-sonnet-4-6", "gpt-5"),
}

_GITHUB_HOSTS = frozenset({"github.com", "www.github.com"})


@dataclass
class ReplState:
    """Mutable session state for one ``hbox`` process."""

    home: Path
    base_url: str
    project_name: str | None = None
    repo_url: str | None = None
    branch: str = "main"
    harness: str = "claude-code"
    model: str | None = None
    workspace_id: str | None = None
    workspace_harness: str | None = None
    runtime_state: str | None = None
    git_auth_mode: str | None = None  # "gh" | "token" | None
    _token: str | None = field(default=None, repr=False)


class HboxExit(Exception):
    """Raised to leave the REPL after ``/exit`` (server already stopped)."""


def main(
    argv: list[str] | None = None,
    *,
    manager: ServerManager | None = None,
    client: HarnessBoxClient | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    home: Path | None = None,
) -> None:
    """Console script entry for ``hbox``."""
    _ = argv
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    inp = stdin if stdin is not None else sys.stdin
    mgr = manager if manager is not None else ServerManager(home=home)

    try:
        info = mgr.ensure()
    except ServerManagerError as exc:
        print(f"hbox: {exc}", file=err)
        raise SystemExit(1) from exc

    how = "started" if info.spawned else "attached"
    print(f"  server: {info.base_url} ({how} pid {info.pid})", file=out)
    print(file=out)

    state = ReplState(
        home=home if home is not None else (mgr.home if manager else default_home()),
        base_url=info.base_url,
    )
    state.home.mkdir(parents=True, exist_ok=True)
    _load_stored_token(state)

    try:
        asyncio.run(
            _run_repl(
                state,
                mgr=mgr,
                client=client,
                stdin=inp,
                stdout=out,
                stderr=err,
            )
        )
    except HboxExit:
        raise SystemExit(0) from None
    except KeyboardInterrupt:
        print(file=out)
        print("  (interrupted — server still running; use /exit to stop)", file=out)
        raise SystemExit(130) from None


async def _run_repl(
    state: ReplState,
    *,
    mgr: ServerManager,
    client: HarnessBoxClient | None,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
) -> None:
    owns_client = client is None
    hb = client if client is not None else HarnessBoxClient(state.base_url)
    try:
        while True:
            try:
                line = await asyncio.to_thread(_read_line, "hbox> ", stdin, stdout)
            except KeyboardInterrupt:
                print(file=stdout)
                print(
                    "  (interrupted — server still running; use /exit to stop)",
                    file=stdout,
                )
                continue

            if line is None:
                print(file=stdout)
                break

            text = line.strip()
            if not text:
                continue

            try:
                await _dispatch(
                    text,
                    state=state,
                    client=hb,
                    mgr=mgr,
                    out=stdout,
                    err=stderr,
                    stdin=stdin,
                )
            except HboxExit:
                raise
            except KeyboardInterrupt:
                print(file=stdout)
                print("  (turn cancelled — server still running)", file=stdout)
            except Exception as exc:  # noqa: BLE001 — keep REPL alive
                print(f"hbox: {exc}", file=stderr)
    finally:
        if owns_client:
            await hb.close()


async def _dispatch(
    text: str,
    *,
    state: ReplState,
    client: HarnessBoxClient,
    mgr: ServerManager,
    out: TextIO,
    err: TextIO,
    stdin: TextIO,
) -> None:
    if text.startswith("/"):
        await _handle_slash(
            text, state=state, client=client, mgr=mgr, out=out, err=err, stdin=stdin
        )
        return
    await _handle_bare_text(text, state=state, client=client, out=out, err=err, stdin=stdin)


async def _handle_slash(
    text: str,
    *,
    state: ReplState,
    client: HarnessBoxClient,
    mgr: ServerManager,
    out: TextIO,
    err: TextIO,
    stdin: TextIO,
) -> None:
    parts = text.split()
    cmd = parts[0].lower()
    args = parts[1:]

    if cmd == "/exit":
        _handle_exit(mgr, out=out)
        raise HboxExit

    if cmd == "/status":
        await _cmd_status(state, client=client, out=out)
        return

    if cmd == "/harness":
        await _cmd_harness(args, state=state, client=client, out=out)
        return

    if cmd == "/model":
        _cmd_model(args, state=state, out=out)
        return

    if cmd == "/project":
        _cmd_project(args, state=state, out=out, err=err)
        return

    if cmd == "/git-auth":
        await _cmd_git_auth(state=state, out=out, err=err, stdin=stdin, prompt=True)
        return

    if cmd == "/add-repo":
        await _cmd_add_repo(args, state=state, client=client, out=out, err=err, stdin=stdin)
        return

    if cmd == "/pause":
        await _cmd_pause_resume("pause", state=state, client=client, out=out, err=err)
        return

    if cmd == "/resume":
        await _cmd_pause_resume("resume", state=state, client=client, out=out, err=err)
        return

    print(f"hbox: unknown command {cmd!r}. Try: {' '.join(_SLASH_COMMANDS)}", file=out)


async def _cmd_status(state: ReplState, *, client: HarnessBoxClient, out: TextIO) -> None:
    if state.workspace_id:
        try:
            info = await client.get_workspace(state.workspace_id)
            _apply_workspace(state, info)
        except Exception:  # noqa: BLE001
            pass

    print(f"  server:     {state.base_url}", file=out)
    print(f"  project:    {state.project_name or '(none)'}", file=out)
    print(f"  workspace:  {state.workspace_id or '(none)'}", file=out)
    print(f"  harness:    {state.harness}", file=out)
    if state.workspace_harness and state.workspace_harness != state.harness:
        print(
            f"  workspace harness: {state.workspace_harness} "
            "(server keeps this until a new conversation)",
            file=out,
        )
    model = state.model or "(unset)"
    print(f"  model:      {model}", file=out)
    print(f"            {model_not_applied_warning()}", file=out)
    print(f"  state:      {state.runtime_state or '(unknown)'}", file=out)
    print(f"  repo:       {state.repo_url or '(none)'}", file=out)
    if state.repo_url:
        print(f"  branch:     {state.branch}", file=out)
    if state.git_auth_mode:
        print(f"  git-auth:   {state.git_auth_mode}", file=out)


async def _cmd_harness(
    args: list[str],
    *,
    state: ReplState,
    client: HarnessBoxClient,
    out: TextIO,
) -> None:
    harnesses = await client.list_harnesses()
    names = [str(h.get("name", "")) for h in harnesses if h.get("name")]
    if not args:
        for name in names:
            mark = " *" if name == state.harness else ""
            print(f"  {name}{mark}", file=out)
        return

    name = args[0]
    if names and name not in names:
        print(f"hbox: unknown harness {name!r}. Available: {', '.join(names)}", file=out)
        return

    state.harness = name
    print(f"  harness set to {name}", file=out)
    if state.workspace_harness and state.workspace_harness != name and state.workspace_id:
        print(
            "  warning: active workspace still uses "
            f"{state.workspace_harness!r} until a new conversation starts",
            file=out,
        )


def _cmd_model(args: list[str], *, state: ReplState, out: TextIO) -> None:
    models = _MODELS_BY_HARNESS.get(state.harness, ())
    if not args:
        if not models:
            print(f"  (no local model list for harness {state.harness!r})", file=out)
            return
        for mid in models:
            mark = " *" if mid == state.model else ""
            print(f"  {mid}{mark}", file=out)
        print(f"  {model_not_applied_warning()}", file=out)
        return

    mid = args[0]
    if models and mid not in models:
        print(f"hbox: unknown model {mid!r}. Try: {', '.join(models)}", file=out)
        return
    state.model = mid
    _save_project(state)
    print(f"  model set to {mid} (local only)", file=out)
    print(f"  {model_not_applied_warning()}", file=out)


def _cmd_project(
    args: list[str],
    *,
    state: ReplState,
    out: TextIO,
    err: TextIO,
) -> None:
    if not args or args[0] != "create":
        print("hbox: usage: /project create [name]", file=out)
        return
    name = args[1] if len(args) > 1 else "default"
    if not re.fullmatch(r"[A-Za-z0-9._-]+", name):
        print("hbox: project name must be alphanumeric / ._- ", file=err)
        return
    state.project_name = name
    _save_project(state)
    print(f"  project {name!r} saved under {state.home / 'projects'}", file=out)


async def _cmd_git_auth(
    *,
    state: ReplState,
    out: TextIO,
    err: TextIO,
    stdin: TextIO,
    prompt: bool,
) -> None:
    mode, token = await asyncio.to_thread(_resolve_git_auth, state, prompt, out, err, stdin)
    state.git_auth_mode = mode
    state._token = token  # noqa: SLF001
    if mode == "gh":
        print("  git-auth: using gh / GITHUB_TOKEN (host resolves; token not sent)", file=out)
    elif mode == "token":
        print("  git-auth: using stored PAT (type=token)", file=out)
    else:
        print("  git-auth: none configured", file=out)


async def _cmd_add_repo(
    args: list[str],
    *,
    state: ReplState,
    client: HarnessBoxClient,
    out: TextIO,
    err: TextIO,
    stdin: TextIO,
) -> None:
    if not args:
        print("hbox: usage: /add-repo <url> [--branch NAME]", file=out)
        return

    url = args[0]
    branch = "main"
    if "--branch" in args:
        idx = args.index("--branch")
        if idx + 1 >= len(args):
            print("hbox: --branch requires a value", file=err)
            return
        branch = args[idx + 1]

    state.repo_url = url
    state.branch = branch
    if state.project_name is None:
        state.project_name = "default"

    need_auth = _is_github_remote(url)
    if need_auth and state.git_auth_mode is None:
        await _cmd_git_auth(state=state, out=out, err=err, stdin=stdin, prompt=True)
        if state.git_auth_mode is None:
            print(
                "hbox: github.com remotes require auth before create (D12). "
                "Run /git-auth or set GITHUB_TOKEN / install gh.",
                file=err,
            )
            return
    elif state.git_auth_mode is None:
        await _cmd_git_auth(state=state, out=out, err=err, stdin=stdin, prompt=False)

    print("  Creating workspace…", file=out)
    try:
        info = await _create_workspace(state, client=client, out=out)
    except WorkspaceCreationError as exc:
        print(f"hbox: create failed: {exc}", file=err)
        return

    _apply_workspace(state, info)
    _save_project(state)
    print(f"  workspace {info.workspace_id} ready", file=out)


async def _cmd_pause_resume(
    action: str,
    *,
    state: ReplState,
    client: HarnessBoxClient,
    out: TextIO,
    err: TextIO,
) -> None:
    if not state.workspace_id:
        print("hbox: no active workspace — /add-repo or send a message first", file=err)
        return
    try:
        if action == "pause":
            info = await client.pause(state.workspace_id)
        else:
            info = await client.resume(state.workspace_id)
    except Exception as exc:  # noqa: BLE001
        print(f"hbox: {action} failed: {exc}", file=err)
        return
    _apply_workspace(state, info)
    print(f"  {action}d — state={info.state}", file=out)


async def _handle_bare_text(
    text: str,
    *,
    state: ReplState,
    client: HarnessBoxClient,
    out: TextIO,
    err: TextIO,
    stdin: TextIO,
) -> None:
    if not state.workspace_id:
        if state.repo_url and _is_github_remote(state.repo_url) and state.git_auth_mode is None:
            await _cmd_git_auth(state=state, out=out, err=err, stdin=stdin, prompt=True)
            if state.git_auth_mode is None:
                print("hbox: auth required before create for github.com remotes", file=err)
                return
        print("  Creating workspace…", file=out)
        try:
            info = await _create_workspace(state, client=client, out=out)
        except WorkspaceCreationError as exc:
            print(f"hbox: create failed: {exc}", file=err)
            return
        _apply_workspace(state, info)
        _save_project(state)

    assert state.workspace_id is not None

    if state.runtime_state == RuntimeState.PAUSED.value:
        progress = CreateProgress(harness=state.harness, out=out)
        progress.resuming()
        try:
            info = await client.resume(state.workspace_id)
        except Exception as exc:  # noqa: BLE001
            print(f"hbox: auto-resume failed: {exc}", file=err)
            return
        _apply_workspace(state, info)

    try:
        async for event in client.prompt(state.workspace_id, text, harness=state.harness):
            frag = format_turn_event(event)
            if frag:
                print(frag, end="", file=out, flush=True)
        print(file=out)
    except Exception as exc:  # noqa: BLE001
        print(f"\nhbox: prompt failed: {exc}", file=err)


async def _create_workspace(
    state: ReplState,
    *,
    client: HarnessBoxClient,
    out: TextIO,
) -> WorkspaceInfo:
    progress = CreateProgress(harness=state.harness, out=out)
    git_auth: Literal["gh", "token"] | None = "gh" if state.git_auth_mode == "gh" else None
    git_token = state._token if state.git_auth_mode == "token" else None  # noqa: SLF001

    seen_id: dict[str, str] = {}

    def on_event(payload: dict[str, Any]) -> None:
        wid = None
        msg = payload.get("message")
        if isinstance(msg, dict):
            wid = msg.get("workspace_id") or msg.get("session_id")
        wid = wid or payload.get("workspace_id") or payload.get("session_id")
        if isinstance(wid, str) and wid and "id" not in seen_id:
            seen_id["id"] = wid
            progress.registered(wid)

    info = await client.create_workspace(
        remote=state.repo_url,
        branch=state.branch,
        harness=state.harness,
        git_auth=git_auth,
        git_token=git_token,
        on_state=progress.on_state,
        on_event=on_event,
    )
    if "id" not in seen_id:
        progress.registered(info.workspace_id)
        progress.on_state(info.state)
    return info


def _handle_exit(mgr: ServerManager, *, out: TextIO) -> None:
    stopped = mgr.stop()
    if stopped:
        print("  server stopped; server.json cleared", file=out)
    else:
        print("  no local server to stop; server.json cleared", file=out)


def _apply_workspace(state: ReplState, info: WorkspaceInfo) -> None:
    state.workspace_id = info.workspace_id
    state.workspace_harness = info.harness
    state.runtime_state = info.state
    if info.remote:
        state.repo_url = info.remote
    if info.branch:
        state.branch = info.branch


def _read_line(prompt: str, stdin: TextIO, stdout: TextIO) -> str | None:
    use_pt = stdin is sys.stdin and hasattr(stdin, "isatty") and stdin.isatty()
    if use_pt:
        try:
            from prompt_toolkit import prompt as pt_prompt
            from prompt_toolkit.completion import WordCompleter

            completer = WordCompleter(list(_SLASH_COMMANDS), sentence=True)
            return pt_prompt(prompt, completer=completer)
        except (ImportError, EOFError):
            pass
        except KeyboardInterrupt:
            raise

    print(prompt, end="", file=stdout, flush=True)
    line = stdin.readline()
    if line == "":
        return None
    return line.rstrip("\n")


def _is_github_remote(url: str) -> bool:
    if url.startswith("git@"):
        # git@github.com:org/repo.git
        host = url.split(":", 1)[0].removeprefix("git@")
        return host in _GITHUB_HOSTS or host.endswith(".github.com")
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return host in _GITHUB_HOSTS


def _resolve_git_auth(
    state: ReplState,
    prompt: bool,
    out: TextIO,
    err: TextIO,
    stdin: TextIO,
) -> tuple[str | None, str | None]:
    if shutil.which("gh") is not None or os.environ.get("GITHUB_TOKEN"):
        return "gh", None

    stored = _read_credentials(state.home)
    if stored:
        return "token", stored

    if not prompt:
        return None, None

    print(
        "  paste a GitHub PAT (stored in ~/.harnessbox/credentials.json, mode 0600):",
        file=out,
    )
    print("  > ", end="", file=out, flush=True)
    token = stdin.readline().strip()
    if not token:
        print("hbox: no token provided", file=err)
        return None, None
    _write_credentials(state.home, token)
    return "token", token


def _credentials_path(home: Path) -> Path:
    return home / "credentials.json"


def _read_credentials(home: Path) -> str | None:
    path = _credentials_path(home)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    token = data.get("github_token") if isinstance(data, dict) else None
    return str(token) if token else None


def _write_credentials(home: Path, token: str) -> None:
    home.mkdir(parents=True, exist_ok=True)
    path = _credentials_path(home)
    path.write_text(json.dumps({"github_token": token}) + "\n", encoding="utf-8")
    path.chmod(0o600)


def _load_stored_token(state: ReplState) -> None:
    token = _read_credentials(state.home)
    if token:
        state.git_auth_mode = "token"
        state._token = token  # noqa: SLF001
        return
    if shutil.which("gh") is not None or os.environ.get("GITHUB_TOKEN"):
        state.git_auth_mode = "gh"


def _projects_dir(home: Path) -> Path:
    return home / "projects"


def _project_path(state: ReplState) -> Path | None:
    if not state.project_name:
        return None
    return _projects_dir(state.home) / f"{state.project_name}.toml"


def _save_project(state: ReplState) -> None:
    path = _project_path(state)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f'name = "{state.project_name}"',
        f'harness = "{state.harness}"',
        f'branch = "{state.branch}"',
    ]
    if state.repo_url:
        lines.append(f'repo = "{state.repo_url}"')
    if state.model:
        lines.append(f'model = "{state.model}"')
    if state.workspace_id:
        lines.append(f'last_workspace_id = "{state.workspace_id}"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
