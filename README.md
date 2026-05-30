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

Scripts can import `cache` and decorate expensive functions with `@cache.memoize`. Results are stored in `.fspython_cache/` and invalidated when call arguments change or when the decorated function **or its same-module callees** (detected via AST) change source code.

```
uv run fspython.py run examples/cache_slow_query.py
```

## Helpers

Start a fspython process in the background, with output redirected to `/tmp/fspython.log`:

```
./start-fspython.sh
```

Stop the fspython process:

```
./stop-fspython.sh
```

To allow plotting via the helpers, add `--allow-gui` to the `serve` command in `start-fspython.sh`.

## Benchmark

Compare cold-start Python vs fspython for a data-science script:

```
uv run python bench_startup.py --runs 3
```
