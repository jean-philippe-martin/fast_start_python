import cache

CALLS = 0


@cache.memoize
def compute(x):
    global CALLS
    CALLS += 1
    return x * 2


if __name__ == "__main__":
    print(f"result={compute(3)} calls={CALLS}")
