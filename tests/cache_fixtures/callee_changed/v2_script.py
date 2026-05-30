import cache


def helper(x):
    return x + 20


CALLS = 0


@cache.memoize
def compute(x):
    global CALLS
    CALLS += 1
    return helper(x)


def main():
    return compute(5)
