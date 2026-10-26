"""Illustrative transfer figure for the preview build (no measurements).

Values mirror paper/placeholders_preview.tex: hidden configurations kept by the untuned
backbone (T0) and the four trained arms, with three seed markers per trained arm.
Palette and fonts follow scripts/plot_formal_partial_evidence.py.
"""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
# Palette of scripts/plot_formal_partial_evidence.py (SLATE1, SLATE3, GRAY2, INK).
COL = {"SLATE1": "#3b4c70", "SLATE3": "#a8b5cf", "GRAY2": "#d2d4d9"}
INK = "#111111"
plt.rcParams.update({"font.family": "Arial", "axes.edgecolor": INK, "xtick.color": INK, "ytick.color": INK,
                     "axes.labelcolor": INK, "axes.linewidth": .6})
MEAN = {"Base model": 20, "Point SFT": 35, "Family SFT": 55, "Point DPO": 40, "Family DPO": 62}
SEEDS = {"Point SFT": (31, 35, 39), "Family SFT": (51, 55, 59), "Point DPO": (36, 40, 44), "Family DPO": (58, 62, 66)}
FACE = {"Base model": COL["GRAY2"], "Point SFT": COL["SLATE3"], "Family SFT": COL["SLATE1"],
        "Point DPO": COL["SLATE3"], "Family DPO": COL["SLATE1"]}
import sys
PLACEHOLDER = "--placeholder" in sys.argv
RED = "#c70d0d"
fig, ax = plt.subplots(figsize=(3.45, 1.45))
names = list(MEAN)
for i, name in enumerate(names):
    if PLACEHOLDER:
        ax.bar(i, MEAN[name], width=.62, color="#f3c6c6", edgecolor=RED, linewidth=.8, hatch="//", zorder=2)
    else:
        ax.bar(i, MEAN[name], width=.62, color=FACE[name], edgecolor=INK, linewidth=.5, zorder=2)
    if name in SEEDS and not PLACEHOLDER:
        ax.scatter([i - .12, i, i + .12], SEEDS[name], s=9, facecolors="white", edgecolors=INK, linewidths=.6, zorder=3)
    ax.text(i, MEAN[name] + 2.5, f"{MEAN[name]}", ha="center", va="bottom", fontsize=5.8, color=RED if PLACEHOLDER else INK)
ax.set_xticks(range(len(names)), [n.replace(" ", "\n", 1) for n in names], fontsize=5.8)
ax.set_ylabel("hidden configurations kept (%)", fontsize=6.2, color=INK)
ax.set_ylim(0, 80); ax.set_yticks([0, 20, 40, 60, 80]); ax.tick_params(axis="y", labelsize=5.8, length=2, width=.5)
ax.tick_params(axis="x", length=0)
for side in ("top", "right"):
    ax.spines[side].set_visible(False)
ax.yaxis.grid(True, color=COL["GRAY2"], linewidth=.4, zorder=0)
handles = [plt.Rectangle((0, 0), 1, 1, facecolor=COL["SLATE3"], edgecolor=INK, linewidth=.5),
           plt.Rectangle((0, 0), 1, 1, facecolor=COL["SLATE1"], edgecolor=INK, linewidth=.5),
           plt.Line2D([], [], marker="o", linestyle="", markersize=3, markerfacecolor="white", markeredgecolor=INK, markeredgewidth=.6)]
if PLACEHOLDER:
    ax.set_title("PLACEHOLDER: dummy values (results pending)", fontsize=6.6, color=RED, pad=3)
else:
    ax.legend(handles, ["point supervision", "family supervision", "training seeds"], fontsize=5.4, frameon=False,
              loc="upper left", handlelength=1.2, handleheight=.9, borderaxespad=0.1, labelspacing=.25)
fig.tight_layout(pad=.3)
out = ROOT / "paper/figures"
stem = "placeholder_e4_transfer" if PLACEHOLDER else "preview_e4_transfer"
fig.savefig(out / (stem + ".pdf"), bbox_inches="tight", pad_inches=0.02)
fig.savefig(out / (stem + ".png"), dpi=220, bbox_inches="tight", pad_inches=0.02)
print("wrote", out / (stem + ".pdf"))
