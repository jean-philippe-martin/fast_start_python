# Plan: `cache.py` — disk-backed memoization for fspython scripts

## Goal

Provide a small library (`cache.py`) that scripts can import and use to decorate expensive functions (e.g. database queries, API calls, heavy computation). Cached results live on **disk** so they survive:

- the script process exiting and being rerun via `fspython run`
- edits to unrelated parts of the script (cache remains valid)

The cache must **miss** (recompute) when:

1. **Call arguments change** — different inputs → different cache entry
2. **The decorated function’s source code changes** — any edit to that function invalidates all of its cached entries

This is intentionally narrower than a general-purpose cache: it optimizes the “iterating on a script around a slow core function” workflow common in data analysis.

---

## Non-goals (v1)

- Distributed / shared cache across machines
- Cache invalidation when *dependencies* change (e.g. a helper function the decorated function calls)
- TTL-based expiry (can be added later)
- Caching async functions
- Security sandboxing of pickled cache files from untrusted sources

---

## Public API (proposed)

```python
import cache

@cache.memoize
def fetch_users(limit: int) -> list[dict]:
    ...

@cache.memoize(cache_dir="/tmp/my_cache")
def expensive_query(sql: str) -> pd.DataFrame:
    ...
```

Optional parameters on the decorator (v1 or v2):

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `cache_dir` | see below | Root directory for cache files |
| `enabled` | `True` | Toggle caching (useful for debugging) |

Module-level helpers (optional, v1):

```python
cache.clear()                      # wipe entire cache root
cache.clear_function(fetch_users)  # wipe entries for one function
```

### Cache directory default

Prefer a project-local directory so cache travels with the workspace and is easy to `.gitignore`:

```
.fspython_cache/
```

Override via:

- decorator argument `cache_dir=...`
- environment variable `FSPYTHON_CACHE_DIR`
- optional module constant set before first use

Add `.fspython_cache/` to `.gitignore`.

---

## Invalidation model

### 1. Arguments → cache key

On each call, build a stable hash from:

- positional args
- keyword args (sorted by key)
- optionally: bound method identity if decorating methods (see edge cases)

**Serialization strategy:**

1. Try JSON encoding for common types (`str`, `int`, `float`, `bool`, `None`, lists/dicts of same)
2. Fall back to `pickle` (highest protocol) for anything else that is picklable
3. If neither works, raise a clear error at decoration/call time: *“cannot cache calls with unhashable/unserializable arguments”*

Hash the canonical byte representation with **SHA-256** (hex string for filenames).

Include the function’s **qualified name** and **defining module** in the key prefix so two functions with identical args never collide.

### 2. Source code → function version

On each call (before lookup):

1. Obtain source via `inspect.getsource(func)`
2. Normalize minimally (strip trailing whitespace on each line) to avoid trivial edit noise
3. Hash → `source_hash`

Compare against `source_hash` stored in that function’s metadata file. If it differs:

- delete all cache entry files for that function
- update metadata with the new `source_hash`
- proceed as a cache miss

This satisfies “invalidate if the source code of **the function itself** has changed” without requiring manual cache clears during development.

**Note:** changes to *other* functions the decorated function calls do **not** invalidate the cache. Document this explicitly.

---

## On-disk layout

```
.fspython_cache/
  meta/
    myscript.fetch_users.json       # per-function metadata
  data/
    myscript.fetch_users/
      a1b2c3d4....pkl               # one file per (function, args) entry
```

### Metadata file (`meta/<cache_key>.json`)

```json
{
  "qualified_name": "myscript.fetch_users",
  "module": "myscript",
  "function_name": "fetch_users",
  "source_hash": "sha256:...",
  "updated_at": "2026-05-30T12:00:00Z"
}
```

### Entry file (`data/<cache_key>/<args_hash>.pkl`)

Pickle payload:

```python
{
  "value": <return value>,
  "created_at": "...",
  "source_hash": "...",   # redundant check at load time
  "args_hash": "...",
}
```

Using pickle for return values matches the data-science stack (DataFrames, numpy arrays, etc.) and keeps v1 simple. Document that cache files must not be shared with untrusted parties.

**Alternative considered:** JSON + parquet for DataFrames — more complex, defer unless pickle proves insufficient.

---

## Decorator execution flow

```
call wrapped(*args, **kwargs)
  │
  ├─ if not enabled → call func directly
  │
  ├─ compute source_hash; load function metadata
  │     └─ if source_hash changed → purge function entries, update meta
  │
  ├─ compute args_hash
  │
  ├─ if entry file exists and entry.source_hash == source_hash
  │     └─ unpickle → return value
  │
  └─ else
        ├─ value = func(*args, **kwargs)
        ├─ pickle value to entry file (atomic write)
        └─ return value
```

### Atomic writes

Write to a temp file in the same directory, then `os.replace()` to the final path. Prevents partial reads if two processes run concurrently.

### Concurrency

fspython may run multiple scripts in parallel (forked children). File-level locking (e.g. `fcntl.flock` on metadata or entry file during read-modify-write) is sufficient for v1 on local disk.

---

## Function identity

Cache key prefix for a function:

```
{module}.{qualname}
```

Examples:

| Function | Cache prefix |
|----------|----------------|
| Top-level in `examples/compute_pandas.py` run via `runpy` | Derive from `__module__` and `__qualname__` at runtime |
| Method `QueryCache.fetch` | `myapp.QueryCache.fetch` (include class name) |

**`runpy.run_path` note:** executed scripts typically have `__name__ == "__main__"`. For stable cache keys across reruns, resolve identity as:

1. Prefer `func.__module__` + `func.__qualname__` when module is not `"__main__"`
2. When module is `"__main__"`, use **`Path(script_path).stem`** + `func.__qualname__`, passed into the decorator or inferred from `func.__code__.co_filename`

This requires the decorator to read `co_filename` for top-level script functions so `examples/compute_pandas.main` (or `compute_pandas.fetch_users`) stays stable across runs.

Document this behavior clearly — cache keys for `__main__` functions are tied to the **file path**, not the string `"__main__"`.

---

## Edge cases and decisions

| Case | v1 behavior |
|------|-------------|
| Lambda / nested function | Support if `inspect.getsource` works; otherwise raise at decorate time |
| Function with no source (REPL, C extension wrapper) | Raise clear error; caching not supported |
| Unhashable / unserializable args | Raise at call time with guidance |
| Unpicklable return value | Cache miss path succeeds but save fails with clear error |
| `self` in methods | Include in args hash (default). Optional later: `@memoize(ignore_self=True)` |
| Mutable args mutated after call | Caller responsibility; args hashed at call time |
| Very large return values | No size limit in v1; document disk usage |
| User deletes `.fspython_cache/` manually | Safe; cache rebuilds on next hit |
| Script renamed | New cache namespace (different file stem); old entries orphaned |

---

## Implementation steps

### Phase 1 — Core (MVP)

1. Create `cache.py` with:
   - `_source_hash(func) -> str`
   - `_args_hash(func_key, args, kwargs) -> str`
   - `_function_key(func) -> str` (handle `__main__` via `co_filename`)
   - `_get_cache_paths(...)` 
   - `@memoize` decorator with disk read/write
   - source-change purge logic
2. Add `.fspython_cache/` to `.gitignore`
3. Unit tests in `tests/test_cache.py`:
   - cache hit / miss on identical args
   - miss after arg change
   - miss after source edit
   - atomic write / reload across fresh `importlib` reload simulating rerun

### Phase 2 — Examples and integration

1. Add `examples/cache_db_query.py` — fake slow function (sleep + random) demonstrating speedup on second run
2. Mention in README under a short “Caching” section

### Phase 3 — Polish (optional)

- `cache.clear()` / `cache.clear_function(fn)`
- `enabled=False` flag
- TTL
- logging at DEBUG for hit/miss/invalidate events

---

## Testing strategy

**Unit tests** (fast, no fspython server):

- Temp cache dir via `tmp_path` fixture
- Decorated pure function; assert second call does not increment a counter
- Rewrite source file / redefine function with different body → assert recompute
- Change one arg → assert recompute

**Integration test** (optional):

- Run example script twice via `fspython run`; second run measurably faster and prints “cache hit” if we add debug logging

---

## Example usage (target)

```python
# examples/cache_slow_query.py
import time
import cache

@cache.memoize
def fetch_sales(region: str) -> dict:
    time.sleep(2)  # stand-in for DB/API
    return {"region": region, "total": 42}

def main():
    print(fetch_sales("North"))  # slow first time
    print(fetch_sales("North"))  # instant from disk

if __name__ == "__main__":
    main()
```

After editing only `main()`, `fetch_sales` cache remains valid. After editing the body of `fetch_sales`, next call recomputes.

---

## Open questions

1. **Pickle vs JSON for args** — pickle is more permissive but less transparent; JSON preferred for arg hashing with pickle fallback?
2. **Cache per user vs per project** — default `.fspython_cache/` in cwd vs `~/.cache/fspython/<project_hash>/`?
3. **Should fspython preload `cache` in the server** — probably unnecessary; scripts import it like any other module.
4. **Expose hit/miss to caller** — e.g. return `(value, from_cache: bool)` — defer unless needed.

Recommendation for v1: project-local `.fspython_cache/`, pickle for values, JSON-then-pickle for args, no TTL.

---

## Success criteria

- [ ] Second identical call returns without re-executing function body
- [ ] Changing any decorated function source invalidates its cache
- [ ] Changing args selects a different entry (or misses)
- [ ] Cache persists after process exit and `fspython run` rerun
- [ ] Works with at least `dict`, `list`, `str`, `int`, and `pandas.DataFrame` return values
- [ ] Clear errors for unsupported cases (no source, unserializable args)
