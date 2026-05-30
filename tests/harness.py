"""Shared helpers for cache and fspython integration tests."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import textwrap
import time
import atexit
import unittest
from dataclasses import dataclass
from pathlib import Path

import cache

ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = TESTS_DIR / "cache_fixtures"
FSPYTHON_SCRIPT = ROOT / "fspython.py"
DEFAULT_HOST = "127.0.0.1"

SCRIPT_NAME = "script.py"
MODULE_NAME = "script_testmod"


def clear_pycache(directory: Path) -> None:
    for pycache in directory.rglob("__pycache__"):
        shutil.rmtree(pycache)


def load_module_from_source(source: str, path: Path, cache_dir: Path):
    """Write source to path and import it as a fresh module."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = textwrap.dedent(source).format(cache_dir=repr(str(cache_dir)))
    path.write_text(rendered, encoding="utf-8")
    clear_pycache(path.parent)
    importlib.invalidate_caches()
    work_dir = str(path.parent.resolve())
    if work_dir not in sys.path:
        sys.path.insert(0, work_dir)
    name = path.stem + "_testmod"
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class ScriptSequenceHarness:
    """Copy fixture versions onto one script path and reload like a rerun."""

    def __init__(self, work_dir: Path, cache_dir: Path) -> None:
        self.work_dir = work_dir
        self.cache_dir = cache_dir
        self.script_path = work_dir / SCRIPT_NAME
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def install_script(self, fixture_path: Path) -> None:
        shutil.copy(fixture_path, self.script_path)
        clear_pycache(self.work_dir)
        importlib.invalidate_caches()

    def install_dependency(self, name: str, fixture_path: Path) -> None:
        shutil.copy(fixture_path, self.work_dir / f"{name}.py")
        clear_pycache(self.work_dir)
        importlib.invalidate_caches()
        sys.modules.pop(name, None)

    def reload(self):
        work_dir = str(self.work_dir.resolve())
        if work_dir not in sys.path:
            sys.path.insert(0, work_dir)

        os.environ["FSPYTHON_CACHE_DIR"] = str(self.cache_dir.resolve())
        sys.modules.pop(MODULE_NAME, None)

        spec = importlib.util.spec_from_file_location(MODULE_NAME, self.script_path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[MODULE_NAME] = module
        spec.loader.exec_module(module)
        return module

    def prepare(
        self,
        *,
        script: Path | None = None,
        deps: dict[str, Path] | None = None,
    ):
        if script is not None:
            self.install_script(script)
        if deps:
            for name, fixture_path in deps.items():
                self.install_dependency(name, fixture_path)
        return self.reload()

    def run_version(self, fixture_path: Path):
        self.install_script(fixture_path)
        return self.reload()


def free_port(host: str = DEFAULT_HOST) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def fspython_cmd(*args: str) -> list[str]:
    return [sys.executable, str(FSPYTHON_SCRIPT), *args]


def send_server_command(host: str, port: int, request: dict, timeout: float = 30) -> dict:
    """Send a JSON control request to a running fspython server."""
    with socket.create_connection((host, port), timeout=timeout) as conn:
        conn.sendall(json.dumps(request, ensure_ascii=False).encode() + b"\n")
        buffer = b""
        while b"\n" not in buffer:
            chunk = conn.recv(65536)
            if not chunk:
                break
            buffer += chunk
        line, _, _rest = buffer.partition(b"\n")
        return json.loads(line.decode())


def wait_for_server(host: str, port: int, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError(f"fspython did not start on {host}:{port} within {timeout}s")


@dataclass
class FspythonRunResult:
    returncode: int
    stdout: str
    stderr: str


class FspythonServer:
    """Start and control a fspython serve process for integration tests."""

    def __init__(
        self,
        port: int | None = None,
        host: str = DEFAULT_HOST,
        project_root: Path = ROOT,
    ) -> None:
        self.host = host
        self.port = port if port is not None else free_port(host)
        self.project_root = project_root
        self.process: subprocess.Popen[str] | None = None
        self._log_handle = None
        self.log_path = project_root / "tests" / "tmp" / f"fspython-{self.port}.log"

    def start(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_handle = self.log_path.open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            fspython_cmd("serve", "--host", self.host, "--port", str(self.port)),
            cwd=self.project_root,
            stdout=self._log_handle,
            stderr=subprocess.STDOUT,
            text=True,
        )
        wait_for_server(self.host, self.port)

    def run_script(
        self,
        script_path: Path | str,
        *,
        cache_dir: Path | None = None,
        cwd: Path | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> FspythonRunResult:
        request_env: dict[str, str] = {}
        if cache_dir is not None:
            request_env["FSPYTHON_CACHE_DIR"] = str(cache_dir.resolve())
        if extra_env:
            request_env.update(extra_env)

        completed = subprocess.run(
            fspython_cmd(
                "run",
                "--host",
                self.host,
                "--port",
                str(self.port),
                str(Path(script_path).resolve()),
            ),
            cwd=cwd or self.project_root,
            env={
                **os.environ,
                **request_env,
            },
            capture_output=True,
            text=True,
        )
        return FspythonRunResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def send_command(self, command: str) -> dict:
        return send_server_command(self.host, self.port, {"command": command})

    def drain(self) -> dict:
        return self.send_command("drain")

    def status(self) -> dict:
        return self.send_command("status")

    def stop(self, timeout: float = 30.0) -> None:
        if self.process is None:
            if self._log_handle is not None:
                self._log_handle.close()
                self._log_handle = None
            return

        if self.process.poll() is None:
            try:
                self.drain()
            except (ConnectionRefusedError, TimeoutError):
                self.process.terminate()
            else:
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    if self.process.poll() is not None:
                        break
                    time.sleep(0.1)
                if self.process.poll() is None:
                    self.process.terminate()

        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        finally:
            self.process = None
            if self._log_handle is not None:
                self._log_handle.close()
                self._log_handle = None


_shared_fspython_server: FspythonServer | None = None


def _server_is_alive(server: FspythonServer | None) -> bool:
    if server is None or server.process is None:
        return False
    if server.process.poll() is not None:
        return False
    try:
        status = send_server_command(server.host, server.port, {"command": "status"}, timeout=2)
    except OSError:
        return False
    return status.get("ok") and status.get("state") == "ready"


def shared_fspython_server() -> FspythonServer:
    """Return the shared test server, starting or restarting it if needed."""
    global _shared_fspython_server

    if _server_is_alive(_shared_fspython_server):
        return _shared_fspython_server  # type: ignore[return-value]

    if _shared_fspython_server is not None:
        _shared_fspython_server.stop()

    _shared_fspython_server = FspythonServer()
    _shared_fspython_server.start()
    return _shared_fspython_server


def shutdown_shared_fspython_server() -> None:
    """Stop the shared test server if it is running."""
    global _shared_fspython_server
    if _shared_fspython_server is not None:
        _shared_fspython_server.stop()
        _shared_fspython_server = None


atexit.register(shutdown_shared_fspython_server)


class SharedFspythonServerTest(unittest.TestCase):
    """Base class for tests that talk to one shared fspython server process."""

    server: FspythonServer

    def setUp(self) -> None:
        self.server = shared_fspython_server()


def parse_calls_output(output: str) -> tuple[int, int]:
    """Parse 'result=6 calls=1' lines printed by fspython cache fixtures."""
    match = re.search(r"result=(\d+) calls=(\d+)", output)
    if not match:
        raise AssertionError(f"Could not parse cache fixture output: {output!r}")
    return int(match.group(1)), int(match.group(2))
