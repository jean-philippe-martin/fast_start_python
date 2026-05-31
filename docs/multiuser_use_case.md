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
        workspace           # symlink to project_foo/workspace/
  project_bar/
    .venv/
    workspace/
    analyses/
    ...
```

The basic idea:

When a user starts an analysis, create a folder under `analyses/` (for example `abcd-01dhj`) and give them a shell whose CWD is that folder. They read shared data via `workspace/` and write scripts in `.`. One `fspython serve` process serves **that project** (typically one serve per project, each using that project's `.venv`).
They have access (through the project .venv) to a `fspython` script that calls `fspython.py` for them.

Expected workflow:

Users write one or more Python programs, iteratively refining them as they explore the data. `fspython` keeps startup fast; `cache` avoids repeating expensive steps when code and inputs are unchanged.

When an output should be shared, copy it to `workspace/` so others see it immediately.

## Instructions for the user

Users run scripts with:

```bash
fspython run my_analysis.py
```

In your script, import `cache` and add `@cache.memoize` decorator to slow functions such as database fetches. This makes it possible
to make updates to the script and then rerun it quickly the second time (as the slow steps will be cache hits).

Input files are in `workspace/`

Packages can be installed as one would expect (they will end up in the project venv and be shared across all analyses):

```bash
uv pip install some-new-package
```

If this is upgrading a package that `fspython serve` is using then we need to restart it for the changes to take effect.


This all works because of the setup work done beforehand. It's explained below.



## Root tools + per-project venv

These two ideas work together:

| Layer | Location | What it controls |
|-------|----------|------------------|
| **Tools** | `root/tools/` | fspython server code, `cache` library — updated once for everyone |
| **Environment** | `project_foo/.venv/` | numpy/pandas versions, project-specific packages — isolated per project |


## Setting up project folder (once per project)

First install the sofware:

```bash
cd /path/to/root/project_foo
uv venv
source .venv/bin/activate
uv pip install -e ../tools/           # live link to root/tools
uv pip install geopandas shapely      # packages this project needs
```

Then start the fspython server (we have one per project, keeping them isolated):

```bash
cd /path/to/root/project_foo
source .venv/bin/activate
fspython serve
```

If you have multiple projects in use at the same time, you need to use a different port for each. Keep track of the port,
so you can write it in FSPYTHON_PORT later.

## Setting up analysis folder (once per analysis folder)

```bash
cd /path/to/root/project_foo/analyses/abcd-01dhj
ln -sf ../../workspace workspace
```

## Setting up the analysis environment (once per shell)

Example environment for user `abcd-01dhj` on `project_foo`:

```bash
export FSPYTHON_HOST=127.0.0.1
export FSPYTHON_PORT=9876

cd /path/to/root/project_foo/analyses/abcd-01dhj
source ../../.venv/bin/activate
```

Inject any needed credentials as environment variables.

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
