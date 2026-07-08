"""Shared pytest fixtures: a real uvicorn subprocess per test.

Every test that needs the app runs it as an actual `uvicorn` subprocess
(not FastAPI's `TestClient`) so websockets, SQLite persistence, and
kill-and-restart behavior are exercised exactly as they would be in
production — `TestClient`'s in-process ASGI transport can't reproduce a
hard process restart, which several persistence tests rely on.
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

PYTHON = sys.executable
REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = REPO_ROOT / "test-artifacts"
ARTIFACTS.mkdir(exist_ok=True)


def _free_port() -> int:
    """Ask the OS for an unused TCP port by binding to port 0 and releasing it.

    Racy in theory (another process could grab the port before uvicorn binds
    it) but reliable enough for local/CI test runs.
    """
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    """The app under test, run as a real uvicorn subprocess so websockets,
    persistence and restarts behave exactly like production.

    Args:
        data_dir: Directory passed to the subprocess as `APP_DATA_DIR`,
            isolating this server's SQLite databases and uploaded audio from
            any other test or the developer's real `data/` directory.
        port: TCP port to bind; a free ephemeral port is chosen if omitted.
    """

    def __init__(self, data_dir: Path, port: int | None = None) -> None:
        self.data_dir = data_dir
        self.port = port or _free_port()
        self.proc: subprocess.Popen | None = None

    @property
    def base_url(self) -> str:
        """This server's HTTP base URL, e.g. `http://127.0.0.1:51234`."""
        return f"http://127.0.0.1:{self.port}"

    @property
    def ws_url(self) -> str:
        """This server's websocket base URL, e.g. `ws://127.0.0.1:51234`."""
        return f"ws://127.0.0.1:{self.port}"

    def start(self) -> None:
        """Launch the uvicorn subprocess and block until `/api/health`
        responds 200, or raise `RuntimeError` after a 30s timeout."""
        env = {**os.environ, "APP_DATA_DIR": str(self.data_dir)}
        self.proc = subprocess.Popen(
            [PYTHON, "-m", "uvicorn", "app.main:app",
             "--host", "127.0.0.1", "--port", str(self.port)],
            cwd=REPO_ROOT,
            env=env,
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"{self.base_url}/api/health", timeout=1).status_code == 200:
                    return
            except httpx.HTTPError:
                time.sleep(0.2)
        self.stop()
        raise RuntimeError("server did not become healthy within 30s")

    def stop(self) -> None:
        """Terminate the subprocess, escalating to `kill()` if it doesn't
        exit within 10s. Safe to call when not running."""
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(10)
            self.proc = None


@pytest.fixture
def server(tmp_path: Path):
    """A running `Server` backed by an isolated `tmp_path`, stopped on teardown.

    Tests that need to simulate a restart (see `test_persistence.py`) call
    `server.stop()` then `server.start()` directly — the fixture only owns
    the initial start and final cleanup.
    """
    s = Server(tmp_path / "data")
    s.start()
    yield s
    s.stop()
