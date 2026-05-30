"""Same compute as v1, with unrelated code appended at the bottom."""
import cache

CALLS = 0


@cache.memoize
def compute(x):
    global CALLS
    CALLS += 1
    return x * 2


def new_helper():
    return "added later"


def report():
    return {"compute": compute(3), "extra": new_helper()}


def main():
    print(f"result={compute(3)} calls={CALLS}")
    print(f"extra={new_helper()}")


if __name__ == "__main__":
    main()
