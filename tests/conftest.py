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
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    """The app under test, run as a real uvicorn subprocess so websockets,
    persistence and restarts behave exactly like production."""

    def __init__(self, data_dir: Path, port: int | None = None):
        self.data_dir = data_dir
        self.port = port or _free_port()
        self.proc: subprocess.Popen | None = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def ws_url(self) -> str:
        return f"ws://127.0.0.1:{self.port}"

    def start(self) -> None:
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
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(10)
            self.proc = None


@pytest.fixture
def server(tmp_path):
    s = Server(tmp_path / "data")
    s.start()
    yield s
    s.stop()
