"""Save an interactive Plotly chart as HTML — works on the fspython fast path.

Open the file in a browser for zoom, pan, and hover tooltips.

    uv run fspython.py run examples/plotly_save_html.py
"""

from pathlib import Path

import plotly.express as px

OUT = Path(__file__).parent / "output" / "plotly_interactive.html"


def main() -> None:
    OUT.parent.mkdir(exist_ok=True)

    fig = px.line(
        x=["Jan", "Feb", "Mar", "Apr", "May"],
        y=[120, 135, 128, 150, 162],
        markers=True,
        title="Monthly values (interactive)",
        labels={"x": "Month", "y": "Value"},
    )
    fig.update_layout(hovermode="x unified")
    fig.write_html(OUT, include_plotlyjs="cdn")

    print(f"Wrote {OUT.resolve()}")


if __name__ == "__main__":
    main()
