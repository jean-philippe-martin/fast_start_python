#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PIDFILE="/tmp/fspython.pid"
LOGFILE="/tmp/fspython.log"

if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "fspython is already running (PID $(cat "$PIDFILE"))"
  exit 0
fi

nohup uv run fspython.py serve >"$LOGFILE" 2>&1 &
echo $! >"$PIDFILE"
echo "Started fspython (PID $(cat "$PIDFILE")), logging to $LOGFILE"
