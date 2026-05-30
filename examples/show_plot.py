"""Open a matplotlib plot window — use this to test GUI via fspython.

Run with a server already up:

    ./start-fspython.sh
    uv run ./fspython.py serve --allow-gui   # if not already started with GUI enabled
    uv run ./fspython.py run --gui examples/show_plot.py

The --gui flag runs the script in a fresh Python process. Matplotlib cannot
open windows in fspython's forked fast path.

Close the plot window when you are done; the run command exits after that.
"""

import matplotlib.pyplot as plt
import numpy as np

x = np.linspace(0, 2 * np.pi, 200)
fig, ax = plt.subplots(num="fspython matplotlib GUI test")
ax.plot(x, np.sin(x), label="sin(x)")
ax.set_title("fspython matplotlib GUI test")
ax.legend()
ax.grid(True, alpha=0.3)
fig.tight_layout()

print("Opening plot window — close it to finish.")
plt.show()
print("Done.")
