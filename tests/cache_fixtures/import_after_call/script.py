import cache

CALLS = 0


@cache.memoize
def compute(x):
    global CALLS
    CALLS += 1
    return x * 2


def run():
    result = compute(5)
    import depmod

    return result, depmod.label
