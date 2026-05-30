"""Save a Plotly chart as PNG — works on the fspython fast path.

Requires kaleido for static image export.

    uv run fspython.py run examples/plotly_save_png.py
"""

from pathlib import Path

import plotly.express as px

OUT = Path(__file__).parent / "output" / "plotly_scatter.png"


def main() -> None:
    OUT.parent.mkdir(exist_ok=True)

    fig = px.scatter(
        x=[1, 2, 3, 4, 5],
        y=[2, 4, 3, 5, 6],
        color=[1, 2, 3, 4, 5],
        title="Scatter with color scale",
        labels={"x": "x", "y": "y", "color": "value"},
    )
    fig.update_layout(width=800, height=500)
    fig.write_image(OUT, scale=2)

    print(f"Wrote {OUT.resolve()}")


if __name__ == "__main__":
    main()
