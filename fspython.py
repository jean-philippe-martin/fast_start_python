#!/usr/bin/env python3
"""Fast-start Python: pre-import data-science libraries and run scripts via fork."""

from __future__ import annotations

import argparse
import errno
import json
import os
import runpy
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9876
DEFAULT_CONNECT_TIMEOUT = 120.0
MAX_REQUEST_BYTES = 1 * 1024 * 1024
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
MAX_CAPTURE_BYTES = 10 * 1024 * 1024

_shutdown_requested = False
_drain_requested = False
_allow_gui = False
_active_children: set[int] = set()
_known_cache_dirs: set[Path] = set()
_last_cache_purge = 0.0
CACHE_PURGE_INTERVAL = 30 * 60


def env_host() -> str:
    """Return the server host from FSPYTHON_HOST, or the default."""
    return os.environ.get("FSPYTHON_HOST", DEFAULT_HOST)


def env_port() -> int:
    """Return the server port from FSPYTHON_PORT, or the default."""
    return int(os.environ.get("FSPYTHON_PORT", DEFAULT_PORT))


def client_connect_timeout() -> float | None:
    """Return client socket timeout while waiting for the server (seconds)."""
    raw = os.environ.get("FSPYTHON_CONNECT_TIMEOUT")
    if raw is None:
        return DEFAULT_CONNECT_TIMEOUT
    raw = raw.strip().lower()
    if raw in {"", "none", "inf", "infinite"}:
        return None
    return float(raw)


def preload_imports() -> None:
    """Import data-science libraries once in the parent before forking."""
    # This will prevent pyplot from opening a window when running in GUI mode.
    os.environ.setdefault("MPLBACKEND", "Agg")
    import matplotlib.pyplot  # noqa: F401
    import numpy  # noqa: F401
    import openpyxl  # noqa: F401
    import pandas  # noqa: F401
    import plotly  # noqa: F401
    import polars  # noqa: F401
    import requests  # noqa: F401
    import scipy  # noqa: F401
    import seaborn  # noqa: F401
    import sklearn  # noqa: F401
    import sqlalchemy  # noqa: F401
    import statsmodels  # noqa: F401


def install_sigchld_handler() -> None:
    """Install a SIGCHLD handler to reap forked child processes."""

    def reap_children(signum: int, frame: object) -> None:
        """Reap any exited child processes without blocking."""
        while True:
            try:
                pid, _status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                break
            if pid == 0:
                break
            if pid > 0:
                _active_children.discard(pid)

    signal.signal(signal.SIGCHLD, reap_children)


def install_shutdown_handlers() -> None:
    """Install SIGINT/SIGTERM handlers that request a graceful shutdown."""

    def request_shutdown(signum: int, frame: object) -> None:
        """Set the shutdown flag so the accept loop can exit."""
        global _shutdown_requested
        _shutdown_requested = True

    signal.signal(signal.SIGINT, request_shutdown)
    signal.signal(signal.SIGTERM, request_shutdown)


def read_json_line(conn: socket.socket, max_size: int = MAX_RESPONSE_BYTES) -> dict[str, Any]:
    """Read a newline-delimited JSON object from the connection."""
    buffer = b""
    while b"\n" not in buffer:
        if len(buffer) >= max_size:
            raise ValueError(f"Message exceeds {max_size} bytes")
        chunk = conn.recv(65536)
        if not chunk:
            break
        buffer += chunk

    if not buffer:
        raise ConnectionError("Connection closed before a complete message was received")

    line, _, _rest = buffer.partition(b"\n")
    if not line.strip():
        raise ValueError("Empty message")

    return json.loads(line.decode())


def send_json_line(conn: socket.socket, payload: dict[str, Any]) -> None:
    """Send a JSON object as a single newline-delimited message."""
    conn.sendall(json.dumps(payload, ensure_ascii=False).encode() + b"\n")


def parse_request(data: dict[str, Any]) -> tuple[Path, Path, list[str], bool, dict[str, str]]:
    """Validate a run request and return script path, cwd, args, gui flag, and env."""
    script = data.get("script")
    if not script or not isinstance(script, str):
        raise ValueError("Missing or invalid 'script' in request")

    script_path = Path(script).expanduser().resolve()
    cwd_value = data.get("cwd")
    if cwd_value:
        cwd = Path(cwd_value).expanduser().resolve()
    else:
        cwd = script_path.parent

    args = data.get("args", [])
    if args is None:
        args = []
    if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
        raise ValueError("'args' must be a list of strings")

    gui = bool(data.get("gui", False))

    raw_env = data.get("env", {})
    if raw_env is None:
        raw_env = {}
    if not isinstance(raw_env, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in raw_env.items()
    ):
        raise ValueError("'env' must be a dict of string keys and values")

    return script_path, cwd, args, gui, raw_env


def attach_to_tty() -> None:
    """Attach stdin/stdout/stderr to the controlling terminal, if available."""
    try:
        tty_fd = os.open("/dev/tty", os.O_RDWR)
    except OSError:
        return

    try:
        for fd in (0, 1, 2):
            os.dup2(tty_fd, fd)
    finally:
        os.close(tty_fd)


def build_response(
    ok: bool,
    code: int,
    message: str = "",
    stdout: str = "",
    stderr: str = "",
    **extra: Any,
) -> dict[str, Any]:
    """Build a standard JSON response payload."""
    payload = {
        "ok": ok,
        "code": code,
        "message": message,
        "stdout": stdout,
        "stderr": stderr,
    }
    payload.update(extra)
    return payload


def _read_pipe(read_fd: int, limit: int = MAX_CAPTURE_BYTES) -> str:
    """Read captured output from a pipe, truncating if it exceeds limit."""
    chunks: list[bytes] = []
    total = 0
    truncated = False

    while True:
        data = os.read(read_fd, min(65536, limit - total + 1))
        if not data:
            break
        if total + len(data) > limit:
            chunks.append(data[: limit - total])
            truncated = True
            break
        chunks.append(data)
        total += len(data)

    text = b"".join(chunks).decode(errors="replace")
    if truncated:
        text += f"\n... output truncated at {limit} bytes ..."
    return text


class CaptureFds:
    """Redirect stdout/stderr file descriptors and capture their output."""

    def __enter__(self) -> CaptureFds:
        """Begin capturing stdout and stderr."""
        self.stdout_r, self.stdout_w = os.pipe()
        self.stderr_r, self.stderr_w = os.pipe()
        self.saved_out = os.dup(1)
        self.saved_err = os.dup(2)
        os.dup2(self.stdout_w, 1)
        os.dup2(self.stderr_w, 2)
        sys.stdout = open(1, "w", encoding="utf-8", closefd=False, buffering=1)
        sys.stderr = open(2, "w", encoding="utf-8", closefd=False, buffering=1)
        self._stdout = ""
        self._stderr = ""
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        """Restore stdout/stderr and read captured output from the pipes."""
        sys.stdout.flush()
        sys.stderr.flush()
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
        os.dup2(self.saved_out, 1)
        os.dup2(self.saved_err, 2)
        os.close(self.stdout_w)
        os.close(self.stderr_w)
        os.close(self.saved_out)
        os.close(self.saved_err)
        self._stdout = _read_pipe(self.stdout_r)
        self._stderr = _read_pipe(self.stderr_r)
        os.close(self.stdout_r)
        os.close(self.stderr_r)
        return False

    @property
    def stdout(self) -> str:
        """Captured stdout after the context exits."""
        return self._stdout

    @property
    def stderr(self) -> str:
        """Captured stderr after the context exits."""
        return self._stderr


def _prepend_sys_path(path: str) -> None:
    if path not in sys.path:
        sys.path.insert(0, path)


def prepare_script_environment(cwd: Path, extra_env: dict[str, str] | None = None) -> None:
    """Configure cwd, optional env vars, and tools path for a script run."""
    if extra_env:
        os.environ.update(extra_env)

    os.chdir(cwd)

    paths_to_prepend: list[str] = [str(cwd.resolve())]
    tools_lib = os.environ.get("FSPYTHON_LIB")
    if tools_lib:
        paths_to_prepend.append(str(Path(tools_lib).expanduser().resolve()))

    for path in reversed(paths_to_prepend):
        _prepend_sys_path(path)


def run_script(
    script_path: Path,
    cwd: Path,
    args: list[str],
    extra_env: dict[str, str] | None = None,
) -> tuple[str, str, int]:
    """Change to cwd, set sys.argv, execute script_path, and capture output."""
    if not script_path.is_file():
        raise FileNotFoundError(f"Script not found: {script_path}")

    code = 0
    with CaptureFds() as capture:
        sys.argv = [str(script_path), *args]
        prepare_script_environment(cwd, extra_env=extra_env)
        try:
            runpy.run_path(str(script_path), run_name="__main__")
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1

    return capture.stdout, capture.stderr, code


def run_script_gui(
    script_path: Path,
    cwd: Path,
    args: list[str],
    extra_env: dict[str, str] | None = None,
) -> tuple[str, str, int]:
    """Run a script in a fresh Python process so matplotlib can open a GUI window."""
    if not script_path.is_file():
        raise FileNotFoundError(f"Script not found: {script_path}")

    attach_to_tty()
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    env.pop("MPLBACKEND", None)

    pythonpath_parts: list[str] = [str(cwd.resolve())]
    tools_lib = env.get("FSPYTHON_LIB")
    if tools_lib:
        pythonpath_parts.append(str(Path(tools_lib).expanduser().resolve()))
    existing_pythonpath = env.get("PYTHONPATH", "")
    if existing_pythonpath:
        pythonpath_parts.append(existing_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)

    completed = subprocess.run(
        [sys.executable, str(script_path), *args],
        cwd=cwd,
        env=env,
    )
    return "", "", completed.returncode


def handle_client(conn: socket.socket, request: dict[str, Any] | None = None) -> None:
    """Run the requested script in a forked child and send the result back."""
    stdout = ""
    stderr = ""
    message = ""
    code = 1
    ok = False

    try:
        if request is None:
            request = read_json_line(conn, max_size=MAX_REQUEST_BYTES)
        script_path, cwd, args, gui, extra_env = parse_request(request)
        if gui and not _allow_gui:
            raise PermissionError(
                "GUI mode is disabled on this server. "
                "Restart with: uv run fspython.py serve --allow-gui"
            )
        if gui:
            stdout, stderr, code = run_script_gui(script_path, cwd, args, extra_env=extra_env)
        else:
            stdout, stderr, code = run_script(script_path, cwd, args, extra_env=extra_env)
        ok = code == 0
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        ok = code == 0
    except Exception as exc:
        message = str(exc)
        code = 1
        ok = False

    send_json_line(conn, build_response(ok=ok, code=code, message=message, stdout=stdout, stderr=stderr))
    os._exit(code if ok else max(code, 1))


def begin_drain(listen_sock: socket.socket) -> None:
    """Stop accepting new run requests and exit once active children finish."""
    global _drain_requested

    if _drain_requested:
        return

    _drain_requested = True
    print("draining...", file=sys.stderr, flush=True)


def handle_drain_request(conn: socket.socket, listen_sock: socket.socket) -> None:
    """Acknowledge a drain request and enter drain mode."""
    begin_drain(listen_sock)
    send_json_line(conn, build_response(ok=True, code=0, message="draining"))
    conn.close()


def server_state() -> str:
    """Return a short label for the current server lifecycle state."""
    if _shutdown_requested:
        return "shutting_down"
    if _drain_requested:
        return "draining"
    return "ready"


def handle_status_request(conn: socket.socket) -> None:
    """Return server state without forking."""
    send_json_line(
        conn,
        build_response(
            ok=True,
            code=0,
            state=server_state(),
            active_children=len(_active_children),
            gui=_allow_gui,
        ),
    )
    conn.close()


def reject_request(conn: socket.socket, message: str) -> None:
    """Reject a request with an error response."""
    send_json_line(conn, build_response(ok=False, code=1, message=message))
    conn.close()


def _record_cache_dir(cwd: Path, extra_env: dict[str, str]) -> None:
    import cache

    _known_cache_dirs.add(cache.cache_dir_for_run(cwd, extra_env))


def _maybe_purge_expired_caches() -> None:
    global _last_cache_purge

    now = time.monotonic()
    if now - _last_cache_purge < CACHE_PURGE_INTERVAL:
        return

    import cache

    for cache_dir in list(_known_cache_dirs):
        try:
            removed = cache.purge_expired(cache_dir)
        except OSError as exc:
            print(f"Cache purge failed for {cache_dir}: {exc}", file=sys.stderr, flush=True)
            continue
        if removed:
            label = "entry" if removed == 1 else "entries"
            print(f"Purged {removed} expired cache {label} from {cache_dir}", file=sys.stderr, flush=True)

    _last_cache_purge = now


def serve(host: str, port: int, allow_gui: bool = False) -> None:
    """Listen for clients and fork to run each script after preloading imports."""
    global _allow_gui

    if not hasattr(os, "fork"):
        print("fspython serve requires Unix fork support", file=sys.stderr)
        raise SystemExit(1)

    _allow_gui = allow_gui

    listen_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        listen_sock.bind((host, port))
    except OSError:
        listen_sock.close()
        raise

    listen_sock.listen(128)
    listen_sock.settimeout(1.0)

    print("Preloading imports...", file=sys.stderr, flush=True)
    preload_imports()
    install_sigchld_handler()
    install_shutdown_handlers()

    import cache

    _known_cache_dirs.add(cache.cache_dir_for_run(Path.cwd(), os.environ))
    _maybe_purge_expired_caches()

    try:
        gui_status = "enabled" if allow_gui else "disabled"
        print(f"fspython ready on {host}:{port} (gui {gui_status})", file=sys.stderr, flush=True)

        while not _shutdown_requested:
            if _drain_requested and not _active_children:
                break

            _maybe_purge_expired_caches()

            try:
                conn, _addr = listen_sock.accept()
            except (TimeoutError, socket.timeout):
                continue
            except OSError as exc:
                if _shutdown_requested or _drain_requested:
                    break
                raise exc

            try:
                request = read_json_line(conn, max_size=MAX_REQUEST_BYTES)
            except Exception as exc:
                reject_request(conn, str(exc))
                continue

            command = request.get("command")
            if command == "drain":
                handle_drain_request(conn, listen_sock)
                continue

            if command == "status":
                handle_status_request(conn)
                continue

            if _drain_requested:
                reject_request(conn, "Server is draining and not accepting new runs")
                continue

            if command is not None:
                reject_request(conn, f"Unknown command: {command!r}")
                continue

            try:
                _script_path, cwd, _args, _gui, extra_env = parse_request(request)
            except Exception as exc:
                reject_request(conn, str(exc))
                continue

            _record_cache_dir(cwd, extra_env)

            pid = os.fork()
            if pid == 0:
                listen_sock.close()
                handle_client(conn, request)
            elif pid < 0:
                reject_request(conn, f"fork failed: {os.strerror(errno.errno)}")
            else:
                _active_children.add(pid)
                conn.close()
                while True:
                    reaped, _status = os.waitpid(pid, os.WNOHANG)
                    if reaped == 0:
                        break
                    if reaped == pid:
                        _active_children.discard(pid)
                        break

        print("Shutting down...", file=sys.stderr, flush=True)
    finally:
        listen_sock.close()


def write_captured_output(stdout: str, stderr: str) -> None:
    """Write captured script output to the client's stdout/stderr."""
    if stdout:
        sys.stdout.write(stdout)
        if not stdout.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()
    if stderr:
        sys.stderr.write(stderr)
        if not stderr.endswith("\n"):
            sys.stderr.write("\n")
        sys.stderr.flush()


def send_command(
    host: str,
    port: int,
    request: dict[str, Any],
    timeout: float | None = None,
) -> dict[str, Any]:
    """Send a control request to the server and return the JSON response."""
    if timeout is None:
        timeout = client_connect_timeout()
    with socket.create_connection((host, port), timeout=timeout) as conn:
        send_json_line(conn, request)
        return read_json_line(conn)


def drain_server(host: str, port: int) -> int:
    """Ask a running server to drain and stop accepting new runs."""
    response = send_command(host, port, {"command": "drain"})

    message = response.get("message", "")
    if message:
        print(message, file=sys.stderr)

    if not response.get("ok"):
        if not message:
            print(f"Unexpected response from server: {response!r}", file=sys.stderr)
        return 1

    return 0


def status_server(host: str, port: int) -> int:
    """Print the running server's state."""
    response = send_command(host, port, {"command": "status"})

    if not response.get("ok"):
        message = response.get("message", "")
        if message:
            print(message, file=sys.stderr)
        else:
            print(f"Unexpected response from server: {response!r}", file=sys.stderr)
        return 1

    state = response.get("state", "unknown")
    active_children = int(response.get("active_children", 0))
    gui = "enabled" if response.get("gui") else "disabled"
    print(f"{state} ({active_children} active children, gui {gui})", file=sys.stderr)
    return 0


def client_env_for_run() -> dict[str, str]:
    """Return client environment variables that should apply to the script child."""
    return {
        key: value
        for key, value in os.environ.items()
        if key.startswith("FSPYTHON_")
    }


def cache_dir_for_client(cwd: Path | None = None) -> Path:
    """Return the cache directory for the current client cwd and environment."""
    import cache

    return cache.cache_dir_for_run(cwd or Path.cwd(), client_env_for_run())


def clearcache_command(cwd: Path | None = None) -> int:
    """Remove all disk cache entries for the current analysis directory."""
    import cache

    root = cache_dir_for_client(cwd)
    existed = root.exists()
    cache.clear(root)
    if existed:
        print(f"Cleared cache at {root}", file=sys.stderr)
    else:
        print(f"No cache at {root}", file=sys.stderr)
    return 0


def run_script_via_server(
    script: str,
    host: str,
    port: int,
    script_args: list[str],
    gui: bool = False,
    extra_env: dict[str, str] | None = None,
) -> int:
    """Connect to the server, request a script run, and return its exit code."""
    env = client_env_for_run()
    if extra_env:
        env.update(extra_env)

    request = {
        "script": str(Path(script).expanduser().resolve()),
        "cwd": str(Path.cwd().resolve()),
        "args": script_args,
        "gui": gui,
        "env": env,
    }

    with socket.create_connection((host, port), timeout=None) as conn:
        send_json_line(conn, request)
        response = read_json_line(conn)

    write_captured_output(response.get("stdout", ""), response.get("stderr", ""))

    message = response.get("message", "")
    if message:
        print(message, file=sys.stderr)

    if "ok" not in response or "code" not in response:
        raise RuntimeError(f"Unexpected response from server: {response!r}")

    ok = bool(response["ok"])
    code = int(response["code"])
    return 0 if ok else code


def normalize_script_args(raw_args: list[str]) -> list[str]:
    """Drop a leading '--' separator before script arguments."""
    if raw_args and raw_args[0] == "--":
        return raw_args[1:]
    return raw_args


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser for serve and run subcommands."""
    parser = argparse.ArgumentParser(description="Fast-start Python for data-science scripts")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_parser = subparsers.add_parser("serve", help="Start the listener process")
    serve_parser.add_argument("--host", default=env_host(), help=f"Host to bind (default: {DEFAULT_HOST})")
    serve_parser.add_argument("--port", type=int, default=env_port(), help=f"Port to bind (default: {DEFAULT_PORT})")
    serve_parser.add_argument(
        "--allow-gui",
        action="store_true",
        help="Allow clients to run scripts with --gui (disabled by default)",
    )

    run_parser = subparsers.add_parser("run", help="Run a script via a running listener")
    run_parser.add_argument("--host", default=env_host(), help=f"Server host (default: {DEFAULT_HOST})")
    run_parser.add_argument("--port", type=int, default=env_port(), help=f"Server port (default: {DEFAULT_PORT})")
    run_parser.add_argument(
        "--gui",
        action="store_true",
        help="Run in a fresh Python process so matplotlib can open a window (required for plots)",
    )
    run_parser.add_argument("script", help="Python file to run")
    run_parser.add_argument(
        "script_args",
        nargs=argparse.REMAINDER,
        help="Arguments forwarded to the script (use -- before script args if needed)",
    )

    drain_parser = subparsers.add_parser("drain", help="Stop accepting new runs on a running server")
    drain_parser.add_argument("--host", default=env_host(), help=f"Server host (default: {DEFAULT_HOST})")
    drain_parser.add_argument("--port", type=int, default=env_port(), help=f"Server port (default: {DEFAULT_PORT})")

    status_parser = subparsers.add_parser("status", help="Show state of a running server")
    status_parser.add_argument("--host", default=env_host(), help=f"Server host (default: {DEFAULT_HOST})")
    status_parser.add_argument("--port", type=int, default=env_port(), help=f"Server port (default: {DEFAULT_PORT})")

    subparsers.add_parser(
        "clearcache",
        help="Remove all disk cache entries for the current directory",
    )

    return parser


def _connection_error(host: str, port: int) -> None:
    print(
        f"Could not connect to fspython at {host}:{port}. "
        "Start the server with: uv run fspython.py serve",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    """Parse CLI arguments and dispatch to serve, run, drain, status, or clearcache."""
    args = build_parser().parse_args(argv)

    if args.command == "serve":
        serve(args.host, args.port, allow_gui=args.allow_gui)
        return 0

    if args.command == "clearcache":
        return clearcache_command()

    if args.command == "drain":
        try:
            return drain_server(args.host, args.port)
        except ConnectionRefusedError:
            _connection_error(args.host, args.port)
            return 1

    if args.command == "status":
        try:
            return status_server(args.host, args.port)
        except ConnectionRefusedError:
            _connection_error(args.host, args.port)
            return 1

    if args.command == "run":
        try:
            return run_script_via_server(
                args.script,
                args.host,
                args.port,
                normalize_script_args(args.script_args),
                gui=args.gui,
            )
        except ConnectionRefusedError:
            _connection_error(args.host, args.port)
            return 1

    return 1


def cli() -> None:
    """Console entry point for setuptools [project.scripts]."""
    raise SystemExit(main())


if __name__ == "__main__":
    raise SystemExit(main())
