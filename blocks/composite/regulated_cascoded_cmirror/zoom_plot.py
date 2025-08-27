import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, ConnectionPatch
from mpl_toolkits.axes_grid1 import make_axes_locatable

path = "/headless/.xschem/simulations"

# Load the saved sweeps
v1, i1 = np.loadtxt(path + '/vanilla.txt', unpack=True)
v2, i2 = np.loadtxt(path + '/biased.txt', unpack=True)
v3, i3 = np.loadtxt(path + '/cascode.txt', unpack=True)

fig, ax = plt.subplots()

# Main plot
ax.plot(v1, i1, label="Vanilla")
ax.plot(v2, i2, label="Biased")
ax.plot(v3, i3, label="Cascode")

ax.set_xlabel("V_out (V)")
ax.set_ylabel("I_out (A)")
ax.set_title("I-V Curves of Different Current Mirrors")
ax.legend()
ax.grid(True)

# --- Side zoom panel (outside the main axes) ---
divider = make_axes_locatable(ax)
ax_zoom = divider.append_axes("right", size="50%", pad=0.6)

# Zoomed x-range
x1, x2 = 0.0, 0.9
# Fixed y-range
y_lo, y_hi = 0.4e-6, 1.2e-6

if y_lo > y_hi:
    y_lo, y_hi = y_hi, y_lo

# Plot zoomed data
ax_zoom.plot(v1, i1, label="Vanilla")
ax_zoom.plot(v2, i2, label="Biased")
ax_zoom.plot(v3, i3, label="Cascode")
ax_zoom.set_xlim(x1, x2)
ax_zoom.set_ylim(y_lo, y_hi)
ax_zoom.grid(True)
ax_zoom.set_xlabel("V_out (V)")
ax_zoom.set_ylabel("I_out (A)")
ax_zoom.set_title("Zoom: early V_out", fontsize=10)

# Rectangle to indicate zoomed region on main plot
rect = Rectangle((x1, y_lo), x2 - x1, y_hi - y_lo,
                 fill=False, linestyle="--", linewidth=1, edgecolor="red", zorder=10)
ax.add_patch(rect)

# Optional connectors
for xy_main, xy_zoom in [((x1, y_hi), (x1, y_hi)), ((x2, y_lo), (x2, y_lo))]:
    con = ConnectionPatch(xyA=xy_zoom, coordsA=ax_zoom.transData,
                          xyB=xy_main, coordsB=ax.transData,
                          linestyle="--", linewidth=0.6, color="red")
    fig.add_artist(con)

plt.tight_layout()
plt.show()
