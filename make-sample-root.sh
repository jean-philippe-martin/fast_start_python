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

FOO_VENV="$PROJECT_FOO/.venv"
FOO_TOOLS="$TOOLS/fspython.py"

cat <<EOF

Done. Sample root created at:
  $SAMPLE_ROOT

Layout:
  sample_root/
    tools/                         shared tools (symlinked to this repo)
    project_foo/
      .venv/                       project Python environment
      workspace/sample_sales.csv   shared input data
      analyses/abcd-01dhj/         example user analysis folder
        summarize_sales.py
        workspace@                 -> ../../workspace
    project_bar/
      workspace/                   empty second project (same pattern)

----------------------------------------------------------------------
Start the fspython server (project_foo)
----------------------------------------------------------------------

  cd $PROJECT_FOO
  source .venv/bin/activate
  python ../tools/fspython.py serve

The server listens on 127.0.0.1:9876 by default. Leave it running in that terminal.

----------------------------------------------------------------------
Run an analysis script (new terminal)
----------------------------------------------------------------------

  cd $ANALYSIS
  source $FOO_VENV/bin/activate
  export PATH="$FOO_VENV/bin:\$PATH"
  python $FOO_TOOLS run summarize_sales.py

You should see a revenue summary printed from workspace/sample_sales.csv.

Other useful commands:

  python $FOO_TOOLS status          # check server state
  python $FOO_TOOLS drain           # stop accepting runs, exit when idle

----------------------------------------------------------------------
Bootstrap project_bar (optional second project)
----------------------------------------------------------------------

  cd $PROJECT_BAR
  uv venv && source .venv/bin/activate
  uv pip install -e ../tools/
  python ../tools/fspython.py serve --port 9877

Use a different port when running multiple projects on one machine.

----------------------------------------------------------------------
Add packages to a project
----------------------------------------------------------------------

  cd $PROJECT_FOO
  source .venv/bin/activate
  uv pip install geopandas
  python ../tools/fspython.py drain    # then restart serve

Tools under sample_root/tools/ point at this repository, so edits here
are visible to all sample projects after you restart their servers.

See docs/multiuser_use_case.md for the full deployment guide.

EOF
