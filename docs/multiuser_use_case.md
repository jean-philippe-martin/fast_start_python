# Multi-user analysis layout

One project folder with shared input files. Multiple users run analyses in isolated working directories while sharing one `fspython serve` process and one Python environment **per project**.

Tools (`fspython`, `cache`) live **once at the deployment root**, not inside each project, so you can update them in one place.

## Folder structure

```
root/
  tools/                    # shared: update once, and all projects are updated
    fspython.py
    cache.py
    pyproject.toml
  project_foo/
    .venv/                  # this project's Python env (serve + all analysis shells)
    workspace/              # shared inputs (csv, etc.)
    analyses/
      abcd-01dhj/           # per-user CWD when they start an analysis
        user_script.py
        .fspython_cache/    # created automatically
        workspace@          # symlink to project_foo/workspace/
  project_bar/
    .venv/
    workspace/
    analyses/
    ...
```

When a user starts an analysis, create a folder under `analyses/` (for example `abcd-01dhj`) and give them a shell whose CWD is that folder. They read shared data via `workspace/` and write scripts in `.`. One `fspython serve` process serves **that project** (typically one serve per project, each using that project's `.venv`).

## Root tools + per-project venv

These two ideas work together:

| Layer | Location | What it controls |
|-------|----------|------------------|
| **Tools** | `root/tools/` | fspython server code, `cache` library — updated once for everyone |
| **Environment** | `project_foo/.venv/` | numpy/pandas versions, project-specific packages — isolated per project |

Install tools into each project venv as an **editable** package pointing at the shared tree:

```bash
cd /path/to/root/project_foo
uv venv
source .venv/bin/activate
uv pip install -e ../tools/           # live link to root/tools
uv pip install geopandas shapely      # packages this project needs
```

Editable install means a change under `root/tools/` is visible without copying files into every project. Restart that project's `fspython serve` after updating `fspython.py` (the parent process loads it once). Changes to `cache.py` usually apply on the next script run in a fork child.

Start the server from the **project** venv, not a separate tools venv:

```bash
cd /path/to/root/project_foo
source .venv/bin/activate
fspython serve
```

## Analysis shell setup

Example environment for user `abcd-01dhj` on `project_foo`:

```bash
export FSPYTHON_HOST=127.0.0.1
export FSPYTHON_PORT=9876
export PATH="/path/to/root/project_foo/.venv/bin:$PATH"

cd /path/to/root/project_foo/analyses/abcd-01dhj
ln -sf ../../workspace workspace@
source /path/to/root/project_foo/.venv/bin/activate
```

Users run scripts with:

```bash
fspython run my_analysis.py
```

Database credentials and other secrets can be injected as normal environment variables in the analysis shell.

## Adding packages later

Install into the **project** venv (not into `root/tools/` unless it's a tool dependency):

```bash
cd /path/to/root/project_foo
source .venv/bin/activate
uv pip install some-new-package
```

Then restart that project's `fspython serve`. Upgrades to preloaded libraries (numpy, pandas, …) only take effect in the warm parent after a restart.

## Updating shared tools

```bash
# edit /path/to/root/tools/fspython.py or cache.py
# then, for each project using the tools:
cd /path/to/root/project_foo && fspython drain   # or stop/start serve
```

No need to touch individual analysis folders or reinstall unless `pyproject.toml` dependencies changed (then `uv pip install -e ../tools/` again in each project venv).

## Cache

- Default cache directory: `{analysis_cwd}/.fspython_cache/`
- Override with `FSPYTHON_CACHE_DIR` (forwarded from client to script)
- `import cache` works via the editable install of `root/tools/` in the project venv

## Expected workflow

Users write one or more Python programs, iteratively refining them as they explore the data. `fspython` keeps startup fast; `cache` avoids repeating expensive steps when code and inputs are unchanged.

When an output should be shared, copy it to `workspace/` so others see it immediately.
