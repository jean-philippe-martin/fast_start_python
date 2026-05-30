"""Save a matplotlib figure as PNG — works on the fspython fast path (Agg backend).

    uv run fspython.py run examples/pyplot_save_png.py
"""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

OUT = Path(__file__).parent / "output" / "pyplot_line.png"


def main() -> None:
    OUT.parent.mkdir(exist_ok=True)

    x = np.linspace(0, 2 * np.pi, 200)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(x, np.sin(x), label="sin(x)")
    ax.plot(x, np.cos(x), label="cos(x)", linestyle="--")
    ax.set_title("Trigonometric functions")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT, dpi=150, bbox_inches="tight")
    plt.close(fig)

    print(f"Wrote {OUT.resolve()}")


if __name__ == "__main__":
    main()
