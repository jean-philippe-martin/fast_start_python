#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

mode="${1:-}"

if [[ "$mode" == "--help" || "$mode" == "-h" ]]; then
  echo "Usage: $0 [--fast-only]"
  echo
  echo "  (default)   Run all tests"
  echo "  --fast-only Skip slow fspython drain tests"
  exit 0
fi

if [[ "$mode" == "--fast-only" ]]; then
  (
    cd tests
    PYTHONPATH="$SCRIPT_DIR" uv run python -m unittest \
      test_cache \
      test_cache_sequences \
      test_cache_fspython \
      test_fspython_integration.FspythonIntegrationTests.test_run_script_via_server \
      test_fspython_integration.FspythonIntegrationTests.test_status_reports_ready \
      -v
  )
elif [[ -n "$mode" ]]; then
  echo "Unknown option: $mode" >&2
  echo "Run '$0 --help' for usage." >&2
  exit 1
else
  uv run python -m unittest discover -s tests -p 'test_*.py' -v
fi
