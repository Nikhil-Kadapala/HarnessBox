"""Local HarnessBox API server lifecycle for ``hbox`` (D13).

Probe an existing pid+port from ``~/.harnessbox/server.json``, or spawn
``harnessbox serve`` (bind-then-record). ``/exit`` stops the recorded process
and clears the pid file (D16).
"""

from __future__ import annotations

import json
import logging
import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("harnessbox.hbox.server_manager")

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8000
_PROBE_PATH = "/v1/harnesses"
_READY_TIMEOUT_S = 15.0
_READY_POLL_S = 0.25
_STOP_WAIT_S = 5.0
_PORT_TRIES = 20
_INSTALL_HINT = "pip install harnessbox  # base wheel includes server deps"


class ServerManagerError(Exception):
    """Raised when the local server cannot be attached or started."""


@dataclass(frozen=True)
class ServerInfo:
    """Live local server coordinates recorded for this hbox session."""

    host: str
    port: int
    pid: int
    started_at: str
    spawned: bool  # True if this process started the server

    @property
    def base_url(self) -> str:
        """HTTP origin for this server (``http://host:port``)."""
        return f"http://{self.host}:{self.port}"


def default_home() -> Path:
    """Return the default ``~/.harnessbox`` directory."""
    return Path.home() / ".harnessbox"


class ServerManager:
    """Attach to or spawn the local API server used by ``hbox``."""

    def __init__(
        self,
        *,
        home: Path | None = None,
        host: str = _DEFAULT_HOST,
        preferred_port: int = _DEFAULT_PORT,
        ready_timeout_s: float = _READY_TIMEOUT_S,
        probe_fn: Any | None = None,
        spawn_fn: Any | None = None,
        pid_alive_fn: Any | None = None,
        kill_fn: Any | None = None,
        find_port_fn: Any | None = None,
        clock: Any | None = None,
    ) -> None:
        self._home = home if home is not None else default_home()
        self._host = host
        self._preferred_port = preferred_port
        self._ready_timeout_s = ready_timeout_s
        self._probe = probe_fn or probe_harnesses
        self._spawn = spawn_fn or _spawn_serve
        self._pid_alive = pid_alive_fn or pid_alive
        self._kill = kill_fn or _kill_process
        self._find_port = find_port_fn or find_free_port
        self._sleep = (clock or time).sleep
        self._monotonic = (clock or time).monotonic
        self._info: ServerInfo | None = None

    @property
    def home(self) -> Path:
        """HarnessBox home directory (pid file + logs)."""
        return self._home

    @property
    def server_json_path(self) -> Path:
        """Path to ``server.json`` (host/port/pid record)."""
        return self._home / "server.json"

    @property
    def server_log_path(self) -> Path:
        """Path to the spawned server's stdout/stderr log."""
        return self._home / "server.log"

    @property
    def info(self) -> ServerInfo | None:
        """Last attached/spawned server for this manager, if any."""
        return self._info

    def ensure(self) -> ServerInfo:
        """Return a healthy local server, attaching or spawning as needed."""
        existing = self._try_attach()
        if existing is not None:
            self._info = existing
            return existing

        info = self._spawn_and_wait()
        self._info = info
        return info

    def stop(self) -> bool:
        """Stop the recorded local server (if still ours) and clear ``server.json``.

        Returns True if a process was signaled, False if there was nothing to stop.
        """
        record = self._read_record()
        signaled = False
        if record is not None:
            pid = int(record["pid"])
            if self._pid_alive(pid):
                self._kill(pid)
                signaled = True
                deadline = self._monotonic() + _STOP_WAIT_S
                while self._pid_alive(pid) and self._monotonic() < deadline:
                    self._sleep(0.1)
                if self._pid_alive(pid):
                    self._kill(pid, force=True)
                    signaled = True
        self._clear_record()
        self._info = None
        return signaled

    def _try_attach(self) -> ServerInfo | None:
        record = self._read_record()
        if record is None:
            return None

        host = str(record.get("host") or self._host)
        port = int(record["port"])
        pid = int(record["pid"])
        started_at = str(record.get("started_at") or "")

        if not self._pid_alive(pid):
            logger.info("Clearing stale server.json (pid %s not alive)", pid)
            self._clear_record()
            return None

        if not self._probe(host, port):
            logger.info("Clearing stale server.json (pid %s alive but probe failed)", pid)
            self._clear_record()
            return None

        return ServerInfo(
            host=host,
            port=port,
            pid=pid,
            started_at=started_at,
            spawned=False,
        )

    def _spawn_and_wait(self) -> ServerInfo:
        self._home.mkdir(parents=True, exist_ok=True)
        port = self._find_port(self._host, self._preferred_port)
        log_path = self.server_log_path

        try:
            proc = self._spawn(self._host, port, log_path)
        except ServerManagerError:
            raise
        except Exception as exc:  # noqa: BLE001 — surface spawn failures clearly
            raise ServerManagerError(
                f"Failed to start local server: {exc}\n{_INSTALL_HINT}"
            ) from exc

        pid = int(proc.pid)
        deadline = self._monotonic() + self._ready_timeout_s
        while self._monotonic() < deadline:
            if not self._pid_alive(pid):
                raise ServerManagerError(
                    f"Local server exited before becoming ready. See {log_path}\n{_INSTALL_HINT}"
                )
            if self._probe(self._host, port):
                started_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                info = ServerInfo(
                    host=self._host,
                    port=port,
                    pid=pid,
                    started_at=started_at,
                    spawned=True,
                )
                self._write_record(info)
                return info
            self._sleep(_READY_POLL_S)

        # Timed out — best-effort cleanup so we do not leave orphans + stale json
        if self._pid_alive(pid):
            self._kill(pid, force=True)
        self._clear_record()
        raise ServerManagerError(
            f"Local server did not become ready within {self._ready_timeout_s:.0f}s. "
            f"See {log_path}\n{_INSTALL_HINT}"
        )

    def _read_record(self) -> dict[str, Any] | None:
        path = self.server_json_path
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Ignoring unreadable server.json at %s", path)
            return None
        if not isinstance(data, dict):
            return None
        if "pid" not in data or "port" not in data:
            return None
        return data

    def _write_record(self, info: ServerInfo) -> None:
        payload = {
            "host": info.host,
            "port": info.port,
            "pid": info.pid,
            "started_at": info.started_at,
        }
        path = self.server_json_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def _clear_record(self) -> None:
        path = self.server_json_path
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove %s", path)


def pid_alive(pid: int) -> bool:
    """Return True if ``pid`` refers to a running process."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we cannot signal it — treat as alive.
        return True
    else:
        return True


def find_free_port(host: str, preferred: int, *, tries: int = _PORT_TRIES) -> int:
    """Bind briefly to claim a port (preferred, then next). Raises if none free."""
    for port in range(preferred, preferred + tries):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind((host, port))
                return port
        except OSError:
            continue
    raise ServerManagerError(f"No free port in range {preferred}–{preferred + tries - 1} on {host}")


def probe_harnesses(host: str, port: int, *, timeout_s: float = 1.0) -> bool:
    """Return True if ``GET /v1/harnesses`` succeeds on the local server."""
    try:
        import httpx
    except ImportError:
        return False

    url = f"http://{host}:{port}{_PROBE_PATH}"
    try:
        with httpx.Client(timeout=timeout_s) as client:
            resp = client.get(url)
            return resp.status_code == 200
    except (httpx.HTTPError, OSError):
        return False


def _spawn_serve(host: str, port: int, log_path: Path) -> subprocess.Popen[bytes]:
    """Start ``harnessbox serve`` with stdout/stderr appended to ``log_path``."""
    # Prefer the same interpreter so editable/uv installs resolve correctly.
    cmd = [
        sys.executable,
        "-m",
        "harnessbox.cli",
        "serve",
        "--host",
        host,
        "--port",
        str(port),
    ]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("ab")
    try:
        return subprocess.Popen(  # noqa: S603 — fixed argv, no shell
            cmd,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError:
        raise
    finally:
        log_file.close()


def _kill_process(pid: int, *, force: bool = False) -> None:
    sig = signal.SIGKILL if force else signal.SIGTERM
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        return
    except PermissionError:
        logger.warning("No permission to signal pid %s", pid)
