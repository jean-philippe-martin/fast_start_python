#!/usr/bin/env python3
"""Compare cold-start Python vs fspython for a data-science script."""

from __future__ import annotations

import argparse
import os
import socket
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_SCRIPT = ROOT / "examples" / "sample_ds.py"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9876


def wait_for_port(host: str, port: int, timeout: float = 120.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError(f"fspython did not start on {host}:{port} within {timeout}s")


def time_command(cmd: list[str], cwd: Path) -> float:
    start = time.perf_counter()
    subprocess.run(cmd, cwd=cwd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return time.perf_counter() - start


def summarize(label: str, samples: list[float]) -> None:
    mean = statistics.mean(samples)
    if len(samples) > 1:
        stdev = statistics.stdev(samples)
        print(f"{label}: {mean:.3f}s mean ({stdev:.3f}s stdev) over {len(samples)} runs")
    else:
        print(f"{label}: {mean:.3f}s")


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark fspython vs normal Python startup time")
    parser.add_argument("--script", type=Path, default=DEFAULT_SCRIPT, help="Script to run")
    parser.add_argument("--runs", type=int, default=3, help="Timed runs per mode")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    script = args.script.resolve()
    if not script.is_file():
        print(f"Script not found: {script}", file=sys.stderr)
        return 1

    env = {**os.environ, "FSPYTHON_HOST": args.host, "FSPYTHON_PORT": str(args.port)}

    python_cmd = [sys.executable, str(script)]
    normal_samples = [time_command(python_cmd, ROOT) for _ in range(args.runs)]

    server = subprocess.Popen(
        [sys.executable, str(ROOT / "fspython.py"), "serve", "--host", args.host, "--port", str(args.port)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        wait_for_port(args.host, args.port)
        fspython_cmd = [sys.executable, str(ROOT / "fspython.py"), "run", str(script), "--host", args.host, "--port", str(args.port)]
        fspython_samples = [time_command(fspython_cmd, ROOT) for _ in range(args.runs)]
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            print("fspython timed out", file=sys.stderr)
            server.kill()
            server.wait()

    print(f"Script: {script}")
    summarize("Normal Python", normal_samples)
    summarize("fspython run", fspython_samples)

    speedup = statistics.mean(normal_samples) / statistics.mean(fspython_samples)
    print(f"Speedup: {speedup:.2f}x")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
