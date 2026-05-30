import cache
from depmod import helper

CALLS = 0


@cache.memoize
def compute(x):
    global CALLS
    CALLS += 1
    return helper(x)


def main():
    return compute(5)
