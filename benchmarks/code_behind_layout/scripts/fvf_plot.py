"""Render actual FVF metal geometry and diagnostic port locations."""
import json
import os
from pathlib import Path
import gdstk
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection

source = Path(os.environ["PROBE_INPUT"])
top, = gdstk.read_gds(source / "fvf7.gds").top_level()
ports = json.loads((source / "debug_ports.json").read_text())
colors = {67: "#777777", 68: "#2379c2", 69: "#c63739", 70: "#279c50", 71: "#ad4dbb"}
for title, bounds in [("local_bias_left", (-88, -53, 43, 64)), ("bias_routes", (-91, 91, -19, 72))]:
    fig, ax = plt.subplots(figsize=(15, 10))
    for layer, color in colors.items():
        polygons = [p.points for p in top.get_polygons() if p.layer == layer and p.datatype == 20]
        ax.add_collection(PolyCollection(polygons, facecolors=color, edgecolors=color, linewidths=.2, alpha=.36, label=str(layer)))
    for name, port in ports.items():
        if name not in ["cmirr_1_fet_A_drain_E", "cmirr_1_fet_A_gate_E", "cmirr_1_welltie_N_top_met_N", "cmirr_1_fet_A_source_E", "cmirr_1_purposegndportscon_N", "cmirr_2_fet_A_drain_E", "cbias_M_3_A_multiplier_0_drain_W", "cbias_M_4_A_multiplier_0_drain_E"]:
            continue
        x, y = port["center_um"]
        ax.plot(x, y, "ko", ms=3)
        ax.annotate(name, (x, y), fontsize=8)
    ax.set_xlim(bounds[:2]); ax.set_ylim(bounds[2:]); ax.set_aspect("equal")
    ax.set_xlabel("um"); ax.set_ylabel("um"); ax.legend(loc="upper right")
    fig.savefig(Path.cwd() / (title + ".png"), dpi=150, bbox_inches="tight")
    plt.close(fig)
