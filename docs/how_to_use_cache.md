# How to use `cache.py`

`cache.py` gives you a `@cache.memoize` decorator that saves function results to disk. Use it for slow work you repeat while iterating on a script — database queries, API calls, heavy transforms — so the second run with the same inputs is fast.

It is designed to work well with fspython: the cache survives between `fspython run` invocations, but updates automatically when your code changes.

## Quick start

```python
import cache

@cache.memoize
def fetch_users(limit: int) -> list[dict]:
    # slow work here
    ...

result = fetch_users(100)
```

Run your script as usual:

```bash
./start-fspython.sh
uv run fspython.py run my_script.py
```

The first call runs the function body. Later calls with the same arguments return the saved result without re-running the body.

See `examples/cache_slow_query.py` for a runnable demo.

## When to use it

Good fits:

- A slow function you call repeatedly while editing other parts of the script
- Expensive reads where the result depends only on the function arguments and your local Python code
- Workflows where restarting the script should not throw away useful results

Poor fits:

- Results that depend on live external state (database rows changing every second, stock prices, etc.)
- Functions imported from other files that you change often (see [What invalidates the cache](#what-invalidates-the-cache))
- Return values that cannot be pickled (open files, sockets, lambdas)

## What invalidates the cache

The cache is keyed by **function identity**, **arguments**, and a **code version hash**.

### 1. Different arguments

```python
fetch_users(100)   # miss → runs body, saves result
fetch_users(100)   # hit
fetch_users(200)   # miss → different args
```

Both positional and keyword arguments are included.

### 2. Changes to the decorated function

If you edit the body of the decorated function, all cached results for that function are discarded on the next call.

### 3. Changes to helpers in the same file

If your decorated function calls other functions **defined in the same `.py` file`**, their source is tracked too. Editing a helper invalidates the cache even if you did not touch the decorated function itself.

```python
def run_query(region: str) -> dict:
    ...

@cache.memoize
def fetch_sales(region: str) -> dict:
    return run_query(region)   # changing run_query invalidates fetch_sales cache
```

This is done by reading the decorated function’s AST and hashing the source of each same-module callee it calls.

### 4. Changes to imported modules in the same folder

At call time, `cache` scans `sys.modules` for Python files in the **same directory as the script** that defines the decorated function. If any of those files change, the cache is invalidated.

This covers imports anywhere in your program flow — including inside `main()` — as long as the module is loaded before the decorated function runs:

```python
@cache.memoize
def fetch_sales(region: str) -> dict:
    return depmod.helper(region)

def main():
    import depmod   # same folder as this script — tracked once loaded
    fetch_sales("North")
```

Modules loaded from other directories (even if on `sys.path`) are not tracked.

### What does *not* invalidate the cache

- Editing a Python file in a **different folder** from the script
- Changing unrelated functions in the same file that the decorated function never calls
- Changing data files, environment variables, or database contents
- Upgrading a third-party library (unless you also change your own code)

If external data can go stale, clear the cache manually (below) or change an argument (e.g. pass a date or schema version).

## Where cache files live

By default, results are stored under:

```
.fspython_cache/
```

This directory is created in the **current working directory** when the script runs. Add it to `.gitignore` (already done in this repo).

Override the location:

```python
@cache.memoize(cache_dir="/tmp/my_project_cache")
def fetch_users(limit: int):
    ...
```

Or set an environment variable before running:

```bash
export FSPYTHON_CACHE_DIR=/tmp/my_project_cache
uv run fspython.py run my_script.py
```

Or set a project-wide default in code before any decorated calls:

```python
import cache

cache.set_cache_dir("/tmp/my_project_cache")
```

## Decorator options

```python
@cache.memoize
def f(): ...

@cache.memoize(cache_dir=".my_cache")
def f(): ...

@cache.memoize(enabled=False)
def f(): ...   # always runs body; useful while debugging
```

You can also use the parameterized form:

```python
@cache.memoize()
def f(): ...
```

## Clearing the cache

Clear everything:

```python
import cache

cache.clear()
```

Clear one function:

```python
cache.clear_function(fetch_users)
```

From the shell, you can delete the cache directory:

```bash
rm -rf .fspython_cache
```

## Requirements and limitations

**Arguments** must be serializable (JSON-friendly types work best; many other picklable types work as a fallback). If arguments cannot be serialized, the decorator raises an error when you call the function.

**Return values** must be pickle-serializable. Common data-science objects (`dict`, `list`, `pandas.DataFrame`, `numpy` arrays) generally work.

**Same-file helpers only.** Only functions defined in the same source file as the decorated function are tracked as dependencies. Calls like `from db import query; query()` are not automatically tracked.

**Simple call patterns.** Dependency detection looks for direct calls such as `helper()` or `self.method()`. Dynamic calls like `getattr(obj, name)()` are not detected.

**Trust your cache files.** Cached entries are stored as pickle files. Do not load cache files from untrusted sources.

## Typical workflow

1. Identify the slow function in your script.
2. Add `@cache.memoize` above it.
3. Start fspython and run the script — first run is slow.
4. Edit plotting, printing, or other code around the slow function — re-run; cache hit, still fast.
5. Edit the slow function or a helper it calls — re-run; cache miss, result refreshes.
6. If external data changed but your code did not, call `cache.clear()` or `cache.clear_function(...)`.

## Example

```bash
uv run fspython.py run examples/cache_slow_query.py   # ~1 second (simulated query)
uv run fspython.py run examples/cache_slow_query.py   # near-instant (cache hit)
```

Edit `run_query` in `examples/cache_slow_query.py` and run again — the cache is invalidated and the slow path runs once more.
