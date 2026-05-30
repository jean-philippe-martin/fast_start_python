"""Pandas aggregation example — prints summary tables to stdout.

    uv run fspython.py run examples/compute_pandas.py
"""

import pandas as pd

SALES = pd.DataFrame(
    {
        "region": ["North", "North", "South", "South", "East", "East"],
        "product": ["A", "B", "A", "B", "A", "B"],
        "revenue": [100, 150, 90, 130, 110, 140],
    }
)


def main() -> None:
    print("Raw data:")
    print(SALES.to_string(index=False))
    print()

    by_region = SALES.groupby("region", as_index=False)["revenue"].agg(
        total="sum",
        mean="mean",
        count="count",
    )
    print("Revenue by region:")
    print(by_region.to_string(index=False))
    print()

    pivot = SALES.pivot_table(
        index="region",
        columns="product",
        values="revenue",
        aggfunc="sum",
        fill_value=0,
    )
    print("Revenue pivot (region x product):")
    print(pivot.to_string())


if __name__ == "__main__":
    main()
