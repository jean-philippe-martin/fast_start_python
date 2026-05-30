"""Demonstrate disk caching with helper dependency invalidation.

    uv run fspython.py run examples/cache_slow_query.py
    uv run fspython.py run examples/cache_slow_query.py   # second run: cache hit
"""

import time

import cache

CALLS = 0


def run_query(region: str) -> dict:
    """Simulate a slow database query."""
    time.sleep(1)
    return {"region": region, "rows": [{"id": 1, "amount": 100}]}


@cache.memoize
def fetch_sales(region: str) -> dict:
    global CALLS
    CALLS += 1
    rows = run_query(region)
    total = sum(row["amount"] for row in rows["rows"])
    return {"region": region, "total": total, "calls": CALLS}


def main() -> None:
    start = time.perf_counter()
    result = fetch_sales("North")
    elapsed = time.perf_counter() - start
    print(f"result={result}  elapsed={elapsed:.2f}s  body_calls={CALLS}")


if __name__ == "__main__":
    main()
