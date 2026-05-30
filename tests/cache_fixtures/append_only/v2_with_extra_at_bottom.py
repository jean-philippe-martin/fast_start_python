"""Same compute as v1, with unrelated code appended at the bottom."""
import cache

CALLS = 0


@cache.memoize
def compute(x):
    global CALLS
    CALLS += 1
    return x * 2


def main():
    return compute(3)


def new_helper():
    return "added later"


def report():
    return {"compute": compute(3), "extra": new_helper()}
