"""Render physical OTA layers for development connectivity diagnosis."""
import json
import os
from pathlib import Path
import gdstk
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection

source = Path(os.environ["PROBE_INPUT"])
top, = gdstk.read_gds(source / "ota7.gds").top_level()
polygons = top.get_polygons()
colors = {67:"#777777", 68:"#2379c2", 69:"#c63739", 70:"#279c50", 71:"#ad4dbb", 89:"#dd9800"}
for label, bounds in [("whole", None), ("input_routes", (-56, 15, -5, 42)), ("cap_corner",(58,82,122,134))]:
    fig, ax = plt.subplots(figsize=(13, 10))
    for layer, color in colors.items():
        points = [p.points for p in polygons if p.layer == layer and (p.datatype == 20 or layer==89)]
        ax.add_collection(PolyCollection(points,facecolors=color,edgecolors=color,linewidths=.15,alpha=.32,label=str(layer)))
    for name, pin in json.loads((source / "pin_bindings.json").read_text()).items():
        x,y = pin["center_um"]
        ax.plot(x,y,"ko",ms=3)
        ax.annotate(name,(x,y),fontsize=9)
    ax.autoscale()
    if bounds:
        ax.set_xlim(bounds[:2]);ax.set_ylim(bounds[2:])
    ax.set_aspect("equal");ax.set_xlabel("um");ax.set_ylabel("um")
    ax.legend(loc="upper right")
    fig.savefig(Path.cwd() / (label + ".png"), dpi=150, bbox_inches="tight")
    plt.close(fig)
