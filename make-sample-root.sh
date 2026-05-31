#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SAMPLE_ROOT="$SCRIPT_DIR/sample_root"
TOOLS="$SAMPLE_ROOT/tools"
PROJECT_FOO="$SAMPLE_ROOT/project_foo"
PROJECT_BAR="$SAMPLE_ROOT/project_bar"
ANALYSIS="$PROJECT_FOO/analyses/abcd-01dhj"

if ! command -v uv >/dev/null 2>&1; then
  echo "error: uv is required (https://docs.astral.sh/uv/)" >&2
  exit 1
fi

echo "Creating sample deployment at: $SAMPLE_ROOT"
rm -rf "$SAMPLE_ROOT"

mkdir -p "$TOOLS" "$PROJECT_FOO/workspace" "$PROJECT_FOO/analyses" "$PROJECT_BAR/workspace" "$PROJECT_BAR/analyses"

for name in fspython.py cache.py pyproject.toml README.md; do
  ln -s "$SCRIPT_DIR/$name" "$TOOLS/$name"
done

cat >"$PROJECT_FOO/workspace/sample_sales.csv" <<'EOF'
region,product,revenue
North,A,100
North,B,150
South,A,90
South,B,130
East,A,110
East,B,140
EOF

mkdir -p "$ANALYSIS"
ln -sf ../../workspace "$ANALYSIS/workspace"

cat >"$ANALYSIS/summarize_sales.py" <<'EOF'
"""Sample analysis: read shared workspace data and print a summary."""

import pandas as pd

df = pd.read_csv("workspace/sample_sales.csv")
summary = df.groupby("region", as_index=False)["revenue"].sum()
print("Revenue by region:")
print(summary.to_string(index=False))
EOF

echo "Creating project_foo/.venv and installing shared tools..."
(
  cd "$PROJECT_FOO"
  uv venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
  uv pip install -e ../tools/
)

cat >"$SAMPLE_ROOT/README.txt" <<EOF
Sample multi-user fspython deployment.

Layout:
  tools/           shared fspython + cache (symlinks to this repo)
  project_foo/     example project with workspace, analyses, and .venv
  project_bar/     second project skeleton (bootstrap its .venv the same way)
EOF

cat <<EOF

Done. Sample root created at:
  $SAMPLE_ROOT

Layout:
  sample_root/
    tools/                         shared tools (symlinked to this repo)
    project_foo/
      .venv/                       project Python environment (already created)
      workspace/sample_sales.csv   shared input data
      analyses/abcd-01dhj/         example analysis folder (workspace symlink ready)
        summarize_sales.py
    project_bar/
      workspace/                   second project skeleton (bootstrap below)

Setup already done for project_foo: .venv, uv pip install -e ../tools/, and
  analyses/abcd-01dhj/workspace -> ../../workspace

----------------------------------------------------------------------
Start the fspython server (once per project, leave running)
----------------------------------------------------------------------

  cd $PROJECT_FOO
  source .venv/bin/activate
  fspython serve

Listens on 127.0.0.1:9876 by default. Use a different --port for each
project if you run more than one server on the same machine.

----------------------------------------------------------------------
Analysis shell (once per terminal session)
----------------------------------------------------------------------

  export FSPYTHON_HOST=127.0.0.1
  export FSPYTHON_PORT=9876

  cd $ANALYSIS
  source ../../.venv/bin/activate

----------------------------------------------------------------------
Run an analysis script
----------------------------------------------------------------------

  fspython run summarize_sales.py

Input files are in workspace/. You should see a revenue summary from
workspace/sample_sales.csv.

Use cache in your scripts: import cache and add @cache.memoize to slow
functions so reruns after edits can skip work on cache hits.

Other useful commands:

  fspython status          # check server state
  fspython drain           # stop accepting runs, exit when idle

----------------------------------------------------------------------
Install packages (from any analysis folder or project root)
----------------------------------------------------------------------

  uv pip install some-new-package

Packages install into project_foo/.venv and are shared across all analyses.
Restart fspython serve only if you upgraded a package the server already
preloaded at startup (numpy, pandas, etc.).

----------------------------------------------------------------------
Bootstrap project_bar (optional second project)
----------------------------------------------------------------------

  cd $PROJECT_BAR
  uv venv && source .venv/bin/activate
  uv pip install -e ../tools/
  fspython serve --port 9877

In analysis shells for project_bar, set FSPYTHON_PORT=9877.

----------------------------------------------------------------------
Update shared tools
----------------------------------------------------------------------

  # edit files under $TOOLS (symlinks to this repo)
  cd $PROJECT_FOO && fspython drain    # then start serve again

Re-run uv pip install -e ../tools/ in each project venv only if
pyproject.toml dependencies changed.

Cache: defaults to .fspython_cache/ in the analysis cwd; override with
FSPYTHON_CACHE_DIR. import cache works via the editable tools install.

See docs/multiuser_use_case.md for the full deployment guide.

EOF
