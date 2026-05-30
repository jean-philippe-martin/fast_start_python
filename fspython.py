#!/usr/bin/env python3
"""Fast-start Python: pre-import data-science libraries and run scripts via fork."""

from __future__ import annotations

import argparse
import os
import runpy
import signal
import socket
import sys
from pathlib import Path

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9876


def env_host() -> str:
    """Return the server host from FSPYTHON_HOST, or the default."""
    return os.environ.get("FSPYTHON_HOST", DEFAULT_HOST)


def env_port() -> int:
    """Return the server port from FSPYTHON_PORT, or the default."""
    return int(os.environ.get("FSPYTHON_PORT", DEFAULT_PORT))


def preload_imports() -> None:
    """Import data-science libraries once in the parent before forking."""
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

    signal.signal(signal.SIGCHLD, reap_children)


def run_script(script_path: Path, cwd: Path) -> None:
    """Change to cwd and execute script_path as __main__."""
    if not script_path.is_file():
        raise FileNotFoundError(f"Script not found: {script_path}")

    os.chdir(cwd)
    runpy.run_path(str(script_path), run_name="__main__")


def read_request(conn: socket.socket) -> tuple[Path, Path]:
    """Read a script path and optional working directory from the client."""
    data = b""
    while b"\n" not in data:
        chunk = conn.recv(4096)
        if not chunk:
            raise ConnectionError("Client disconnected before sending a script path")
        data += chunk

    lines = data.decode().splitlines()
    if not lines or not lines[0].strip():
        raise ValueError("Missing script path")

    script_path = Path(lines[0].strip()).expanduser().resolve()
    cwd = Path(lines[1].strip()).expanduser().resolve() if len(lines) > 1 and lines[1].strip() else script_path.parent
    return script_path, cwd


def send_response(conn: socket.socket, ok: bool, message: str, code: int = 0) -> None:
    """Send a status line with exit code and optional message to the client."""
    status = "OK" if ok else "ERR"
    conn.sendall(f"{status} {code} {message}\n".encode())


def handle_client(conn: socket.socket) -> None:
    """Run the requested script in a forked child and send the result back."""
    try:
        script_path, cwd = read_request(conn)
        run_script(script_path, cwd)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        send_response(conn, ok=code == 0, message="", code=code)
        os._exit(code)
    except Exception as exc:
        send_response(conn, ok=False, message=str(exc), code=1)
        os._exit(1)

    send_response(conn, ok=True, message="", code=0)
    os._exit(0)


def serve(host: str, port: int) -> None:
    """Preload imports, then listen for clients and fork to run each script."""
    preload_imports()
    install_sigchld_handler()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listen_sock:
        listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listen_sock.bind((host, port))
        listen_sock.listen(128)
        print(f"fspython listening on {host}:{port}", file=sys.stderr, flush=True)

        while True:
            conn, _addr = listen_sock.accept()
            pid = os.fork()
            if pid == 0:
                listen_sock.close()
                try:
                    handle_client(conn)
                finally:
                    conn.close()
            conn.close()


def parse_response(raw: str) -> tuple[bool, int, str]:
    """Parse a server response into success flag, exit code, and message."""
    line = raw.strip().splitlines()[0] if raw.strip() else ""
    parts = line.split(" ", 2)
    if len(parts) < 2 or parts[0] not in {"OK", "ERR"}:
        raise RuntimeError(f"Unexpected response from server: {raw!r}")

    ok = parts[0] == "OK"
    code = int(parts[1])
    message = parts[2] if len(parts) > 2 else ""
    return ok, code, message


def run_script_via_server(script: str, host: str, port: int) -> int:
    """Connect to the server, request a script run, and return its exit code."""
    script_path = Path(script).expanduser().resolve()
    cwd = Path.cwd().resolve()

    with socket.create_connection((host, port), timeout=30) as conn:
        conn.sendall(f"{script_path}\n{cwd}\n".encode())
        response = conn.recv(4096).decode()

    ok, code, message = parse_response(response)
    if message:
        print(message, file=sys.stderr)
    return 0 if ok else code


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser for serve and run subcommands."""
    parser = argparse.ArgumentParser(description="Fast-start Python for data-science scripts")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_parser = subparsers.add_parser("serve", help="Start the listener process")
    serve_parser.add_argument("--host", default=env_host(), help=f"Host to bind (default: {DEFAULT_HOST})")
    serve_parser.add_argument("--port", type=int, default=env_port(), help=f"Port to bind (default: {DEFAULT_PORT})")

    run_parser = subparsers.add_parser("run", help="Run a script via a running listener")
    run_parser.add_argument("script", help="Python file to run")
    run_parser.add_argument("--host", default=env_host(), help=f"Server host (default: {DEFAULT_HOST})")
    run_parser.add_argument("--port", type=int, default=env_port(), help=f"Server port (default: {DEFAULT_PORT})")

    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse CLI arguments and dispatch to serve or run."""
    args = build_parser().parse_args(argv)

    if args.command == "serve":
        serve(args.host, args.port)
        return 0

    if args.command == "run":
        try:
            return run_script_via_server(args.script, args.host, args.port)
        except ConnectionRefusedError:
            print(
                f"Could not connect to fspython at {args.host}:{args.port}. "
                "Start the server with: uv run fspython.py serve",
                file=sys.stderr,
            )
            return 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
