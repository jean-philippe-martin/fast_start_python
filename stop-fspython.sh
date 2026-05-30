#!/usr/bin/env bash
set -euo pipefail

PIDFILE="/tmp/fspython.pid"

if [[ ! -f "$PIDFILE" ]]; then
  echo "No PID file found; fspython may not be running"
  exit 1
fi

PID=$(cat "$PIDFILE")
if ! kill -0 "$PID" 2>/dev/null; then
  echo "fspython is not running (stale PID file)"
  rm -f "$PIDFILE"
  exit 1
fi

kill "$PID"
rm -f "$PIDFILE"
echo "Stopped fspython (PID $PID)"
