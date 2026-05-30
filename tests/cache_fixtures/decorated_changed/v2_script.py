import cache

CALLS = 0


@cache.memoize
def compute(x):
    global CALLS
    CALLS += 1
    return x * 3


def main():
    return compute(3)
