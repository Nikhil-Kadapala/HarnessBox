"""Unit tests for hbox server_manager and /exit (D13 / D16)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from harnessbox.hbox.app import main
from harnessbox.hbox.server_manager import (
    ServerInfo,
    ServerManager,
    ServerManagerError,
    find_free_port,
)


@dataclass
class _FakeClock:
    now: float = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class _FakeProc:
    pid: int


class _ProbeScript:
    """Callable probe that returns a scripted sequence of bools, then last value."""

    def __init__(self, results: list[bool]) -> None:
        self.results = list(results)
        self.calls: list[tuple[str, int]] = []

    def __call__(self, host: str, port: int) -> bool:
        self.calls.append((host, port))
        if self.results:
            return self.results.pop(0)
        return False


def _write_server_json(home: Path, *, host: str, port: int, pid: int) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "server.json").write_text(
        json.dumps({"host": host, "port": port, "pid": pid, "started_at": "t0"}) + "\n",
        encoding="utf-8",
    )


def test_ensure_attaches_when_pid_alive_and_probe_ok(tmp_path: Path) -> None:
    _write_server_json(tmp_path, host="127.0.0.1", port=8000, pid=4242)
    probe = _ProbeScript([True])
    spawned: list[Any] = []

    mgr = ServerManager(
        home=tmp_path,
        probe_fn=probe,
        spawn_fn=lambda *a, **k: spawned.append((a, k)) or _FakeProc(99),
        pid_alive_fn=lambda pid: pid == 4242,
    )

    info = mgr.ensure()
    assert info == ServerInfo(
        host="127.0.0.1",
        port=8000,
        pid=4242,
        started_at="t0",
        spawned=False,
    )
    assert spawned == []
    assert probe.calls == [("127.0.0.1", 8000)]
    assert (tmp_path / "server.json").is_file()


def test_ensure_clears_stale_pid_and_spawns(tmp_path: Path) -> None:
    _write_server_json(tmp_path, host="127.0.0.1", port=8000, pid=1)
    clock = _FakeClock()

    # pid 1 dead → clear without probe; then spawn on free port
    alive = {9999: True}

    def pid_alive(pid: int) -> bool:
        return alive.get(pid, False)

    def spawn(host: str, port: int, log_path: Path) -> _FakeProc:
        assert host == "127.0.0.1"
        assert port == 8100
        assert log_path == tmp_path / "server.log"
        return _FakeProc(9999)

    # After spawn: first probe fail, then success
    probe_after = _ProbeScript([False, True])

    # Use a custom probe that fails only during attach path... attach never
    # probes because pid is dead. Spawn path uses probe_after.
    mgr = ServerManager(
        home=tmp_path,
        preferred_port=8100,
        probe_fn=probe_after,
        spawn_fn=spawn,
        pid_alive_fn=pid_alive,
        find_port_fn=lambda host, preferred: preferred,
        clock=clock,
    )

    info = mgr.ensure()
    assert info.spawned is True
    assert info.pid == 9999
    assert info.port == 8100
    record = json.loads((tmp_path / "server.json").read_text(encoding="utf-8"))
    assert record["pid"] == 9999
    assert record["port"] == 8100
    assert "started_at" in record


def test_ensure_clears_when_pid_alive_but_probe_fails_then_spawns(tmp_path: Path) -> None:
    _write_server_json(tmp_path, host="127.0.0.1", port=8000, pid=50)
    clock = _FakeClock()
    calls: list[tuple[str, int]] = []

    def probe(host: str, port: int) -> bool:
        calls.append((host, port))
        # First call is attach (fails); second is after spawn (ok)
        return len(calls) > 1

    mgr = ServerManager(
        home=tmp_path,
        preferred_port=9000,
        probe_fn=probe,
        spawn_fn=lambda host, port, log: _FakeProc(77),
        pid_alive_fn=lambda pid: pid in {50, 77},
        find_port_fn=lambda host, preferred: preferred,
        clock=clock,
    )

    info = mgr.ensure()
    assert info.spawned is True
    assert info.pid == 77
    assert calls[0] == ("127.0.0.1", 8000)
    assert calls[1] == ("127.0.0.1", 9000)


def test_ensure_spawn_timeout_kills_and_raises(tmp_path: Path) -> None:
    clock = _FakeClock()
    killed: list[tuple[int, bool]] = []

    def kill(pid: int, *, force: bool = False) -> None:
        killed.append((pid, force))

    mgr = ServerManager(
        home=tmp_path,
        ready_timeout_s=0.5,
        probe_fn=lambda host, port: False,
        spawn_fn=lambda host, port, log: _FakeProc(123),
        pid_alive_fn=lambda pid: pid == 123,
        find_port_fn=lambda host, preferred: preferred,
        kill_fn=kill,
        clock=clock,
    )

    with pytest.raises(ServerManagerError, match="did not become ready"):
        mgr.ensure()

    assert killed == [(123, True)]
    assert not (tmp_path / "server.json").exists()


def test_ensure_spawn_early_exit_raises(tmp_path: Path) -> None:
    clock = _FakeClock()

    mgr = ServerManager(
        home=tmp_path,
        probe_fn=lambda host, port: False,
        spawn_fn=lambda host, port, log: _FakeProc(5),
        pid_alive_fn=lambda pid: False,
        find_port_fn=lambda host, preferred: preferred,
        clock=clock,
    )

    with pytest.raises(ServerManagerError, match="exited before becoming ready"):
        mgr.ensure()


def test_stop_signals_pid_and_clears_json(tmp_path: Path) -> None:
    _write_server_json(tmp_path, host="127.0.0.1", port=8000, pid=321)
    clock = _FakeClock()
    signals: list[tuple[int, bool]] = []
    alive = {321: True}

    def kill(pid: int, *, force: bool = False) -> None:
        signals.append((pid, force))
        alive[pid] = False

    mgr = ServerManager(
        home=tmp_path,
        pid_alive_fn=lambda pid: alive.get(pid, False),
        kill_fn=kill,
        clock=clock,
    )
    mgr._info = ServerInfo(  # noqa: SLF001 — set session info for realism
        host="127.0.0.1",
        port=8000,
        pid=321,
        started_at="t0",
        spawned=True,
    )

    assert mgr.stop() is True
    assert signals == [(321, False)]
    assert not (tmp_path / "server.json").exists()
    assert mgr.info is None


def test_stop_noop_when_no_record(tmp_path: Path) -> None:
    mgr = ServerManager(home=tmp_path)
    assert mgr.stop() is False
    assert not (tmp_path / "server.json").exists()


def test_find_free_port_skips_occupied() -> None:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
        holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        holder.bind(("127.0.0.1", 0))
        occupied = holder.getsockname()[1]
        # Prefer the occupied port; should advance to a free one
        free = find_free_port("127.0.0.1", occupied, tries=5)
        assert free != occupied
        assert free > occupied


def test_app_exit_stops_server(tmp_path: Path) -> None:
    from io import StringIO

    clock = _FakeClock()
    stopped: list[bool] = []

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
            stopped.append(True)
            return True

    stdin = StringIO("/exit\n")
    with pytest.raises(SystemExit) as exc:
        main(manager=_Mgr(home=tmp_path, clock=clock), stdin=stdin, stdout=StringIO())
    assert exc.value.code == 0
    assert stopped == [True]


def test_app_ensure_failure_exits_one(tmp_path: Path) -> None:
    from io import StringIO

    class _Mgr(ServerManager):
        def ensure(self) -> ServerInfo:
            raise ServerManagerError("boom\npip install harnessbox")

    err = StringIO()
    with pytest.raises(SystemExit) as exc:
        main(manager=_Mgr(home=tmp_path), stdin=StringIO(), stdout=StringIO(), stderr=err)
    assert exc.value.code == 1
    assert "boom" in err.getvalue()
