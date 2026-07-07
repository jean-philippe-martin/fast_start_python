# Fast Start Python

The idea: a Python that starts quickly with a bunch of imports for data analysis. We pre-start a Python process with the right imports and it listens to a port and gets messages that specify a python file, and:

- it forks
- imports that python file
- runs it

Data analysis libraries it imports:

- numpy
- pandas
- scipy
- matplotlib.pyplot (as pyplot)
- seaborn
- plotly
- statsmodels
- scikit-learn (as sklearn)
- polars
- sqlalchemy
- openpyxl
- requests

## Command line

Start the listener process:

```
uv run fspython.py serve
```

Connect to the server and run a script:

```
uv run fspython.py run somefile.py
```

Pass arguments to the script (use `--` before script args if needed):

```
uv run fspython.py run somefile.py -- --foo bar
```

Server and client options (`--host`, `--port`) go **before** the script path:

```
uv run fspython.py run --port 9876 somefile.py
```

## Matplotlib and plotting

The server preloads matplotlib with the **Agg** backend — a non-interactive renderer that draws in memory and is safe to use after `fork()`. This is ideal for the fast path: saving figures with `savefig()`, benchmarks, and scripts that don't open windows.

Interactive plots (`plt.show()`) need a GUI backend and **cannot** run on the fork fast path. For those, use **GUI mode**:

1. Start the server with GUI mode allowed (disabled by default):

```
uv run fspython.py serve --allow-gui
```

2. Run the script with `--gui` (spawns a fresh Python process attached to your terminal):

```
uv run fspython.py run --gui examples/show_plot.py
```

If you try `--gui` against a server started without `--allow-gui`, the run is rejected with an error.

GUI mode skips the preloaded-import fast path (matplotlib loads cold), but windows work reliably.

Matplotlib does not export interactive HTML; use Plotly for that (see examples below).

## Examples

All of these work on the fast path unless noted. Generated files go to `examples/output/`.

| Script | What it does |
|--------|----------------|
| `examples/pyplot_save_png.py` | matplotlib line plot → PNG |
| `examples/plotly_save_png.py` | Plotly scatter → PNG |
| `examples/plotly_save_html.py` | Plotly line chart → interactive HTML |
| `examples/compute_pandas.py` | groupby / pivot, prints tables |
| `examples/compute_regression.py` | OLS regression, prints coefficients |
| `examples/cache_slow_query.py` | disk cache demo with helper invalidation |
| `examples/show_plot.py` | live plot window (`run --gui`, server needs `--allow-gui`) |

## Caching

Scripts can import `cache` and decorate expensive functions with `@cache.memoize`. Results are stored on disk (default: `.fspython_cache/`) and survive between `fspython run` invocations.

On the **fast path** (normal `run`, not `--gui`), your script runs in a forked child with the preloaded imports already warm. A plain `import cache` in your script is all you need — no special server setup.

Cache entries are invalidated when:

- call arguments change
- the decorated function’s source changes
- same-file functions **called by** the decorated function change
- same-folder `.py` modules already imported before the call change
- an entry is older than **30 minutes**

Run from the **project root** (or any directory where `cache.py` is importable via `cwd` on `sys.path`):

```
uv run fspython.py run examples/cache_slow_query.py
uv run fspython.py run examples/cache_slow_query.py   # cache hit
```

To use a custom cache directory, set `FSPYTHON_CACHE_DIR` in the environment before `fspython run` (it is forwarded to the script process):

```
export FSPYTHON_CACHE_DIR=/tmp/my_cache
uv run fspython.py run examples/cache_slow_query.py
```

See `docs/how_to_use_cache.md` for full details.

## Server control

Check whether the server is running:

```
uv run fspython.py status
```

Gracefully stop accepting new runs and exit once in-flight scripts finish:

```
uv run fspython.py drain
```

Clear the disk cache for the current directory (respects `FSPYTHON_CACHE_DIR`):

```
fspython clearcache
```

While draining, `run` requests are rejected; `status` still works. When all active children complete, the server exits.

The server also purges expired disk cache entries (older than 30 minutes) about every 30 minutes for cache directories used by recent runs.

## Helpers

Start a fspython process in the background, with output redirected to `/tmp/fspython.log`:

```
./start-fspython.sh
```

Stop the fspython process (immediate SIGTERM):

```
./stop-fspython.sh
```

For a graceful shutdown that waits for in-flight runs, use drain instead:

```
uv run fspython.py drain
```

To allow plotting via the helpers, add `--allow-gui` to the `serve` command in `start-fspython.sh`.

## Project packages (multi-user)

Shared tools live once at the deployment root; each project has its own `.venv` for package versions:

```
root/
  tools/              # fspython + cache — update once
  project_foo/
    .venv/            # this project's env (serve + all analysis shells)
    analyses/...
```

Bootstrap a project:

```
cd root/project_foo
uv venv && source .venv/bin/activate
uv pip install -e ../tools/
uv pip install geopandas
fspython serve
```

Restart a project's server after tool or dependency updates. See `docs/multiuser_use_case.md` for the full layout.

## Tests

Run the test suite:

```
./run-tests.sh
```

Skip the slow fspython drain tests (~7s instead of ~17s):

```
./run-tests.sh --fast-only
```

## Benchmark

Compare cold-start Python vs fspython for a data-science script:

```
uv run python bench_startup.py --runs 3
```

On  my machine this reports: `Speedup: 5.57x`

