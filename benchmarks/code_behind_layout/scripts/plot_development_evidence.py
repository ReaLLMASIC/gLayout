"""Render actual development measurements and GDS without formal-result claims."""
import json
from pathlib import Path

import gdstk
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection
from matplotlib.patches import Patch
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "paper/figures"
RAW = ROOT / "results/raw/checkpoints/phase0_20261019T0155Z/runs/phase0"


def save(figure, name):
    figure.savefig(OUT / (name + ".pdf"), bbox_inches="tight")
    figure.savefig(OUT / (name + ".png"), dpi=220, bbox_inches="tight")
    plt.close(figure)


def pool_figure():
    pool = json.loads((ROOT / "results/derived/e2_development_five_t_pool.json").read_text())
    analysis = json.loads((ROOT / "results/derived/e2_development_five_t_analysis.json").read_text())
    table = sorted(pool["pool_table"], key=lambda r: r["candidate_id"])
    measured = {r["candidate_id"]: r for r in analysis["rows"] if r.get("worst_corner_ugb_Hz") is not None}
    figure, axes = plt.subplots(1, 2, figsize=(9.5, 3.05), gridspec_kw={"width_ratios": [1, 1.35]})
    rows = list(measured.values())
    scatter = axes[0].scatter([r["post_PEX_one_pole_proxy_Hz"] / 1e6 for r in rows],
        [r["worst_corner_ugb_Hz"] / 1e6 for r in rows], c=[r["footprint_area_um2"] / 1e3 for r in rows],
        cmap="viridis", s=45, edgecolors="white", linewidths=.5)
    for row in rows:
        if row["candidate_id"] in analysis["predefined_near_frontier_ids"]:
            axes[0].scatter(row["post_PEX_one_pole_proxy_Hz"] / 1e6, row["worst_corner_ugb_Hz"] / 1e6,
                s=92, facecolors="none", edgecolors="#15283e", linewidths=1)
    axes[0].set(xlabel="Post-PEX total-RC heuristic (MHz)", ylabel="Worst-corner UGB (MHz)",
        title="(a) 14 complete outcomes / 16 attempts")
    axes[0].ticklabel_format(axis="y", style="plain", useOffset=False)
    axes[0].text(.03, .20, "Broad pool: 26 / 91 pair reversals\nOutlined area frontier: 0 / 3 reversals",
        transform=axes[0].transAxes, fontsize=7.5, va="bottom")
    figure.colorbar(scatter, ax=axes[0], pad=.02, label="Footprint (10³ µm²)")
    stages = ["generation", "geometry", "DRC", "LVS", "PEX", "electrical"]
    colors = ["#466991", "#b7c9df", "#6b9e8b", "#d0b45c", "#bf8464", "#795c95"]
    bottom = np.zeros(len(table))
    for stage, color in zip(stages, colors):
        values = np.array([r["stage_wall_seconds"][stage] for r in table])
        axes[1].bar(np.arange(len(table)), values, bottom=bottom, color=color, label=stage, width=.8)
        bottom += values
    for i, row in enumerate(table):
        if not row["full_flow_complete"]:
            axes[1].text(i, bottom[i] + 3, "×", ha="center", fontsize=12, color="#ae3a36")
    axes[1].set(xlabel="Frozen candidate ID", ylabel="Summed stage wall time (s)",
        title="(b) Every attempt retains its measured cost", xticks=np.arange(len(table)),
        xticklabels=[r["candidate_id"] for r in table])
    axes[1].tick_params(axis="x", rotation=60, labelsize=7)
    axes[1].set_ylim(0, 225)
    axes[1].legend(ncol=3, loc="upper right", fontsize=6.5, frameon=False)
    axes[1].text(.98, .80, "× incomplete transient", ha="right", transform=axes[1].transAxes, fontsize=7)
    for ax in axes:
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", alpha=.15)
        ax.set_axisbelow(True)
    figure.tight_layout(w_pad=1.8)
    save(figure, "development_fidelity_and_cost")
    return {"pool": pool["pool_id"], "all_attempts": len(table), "complete": len(rows),
        "scope": "Development fixed pool only; total RC requires full physical extraction; no cheap-fidelity or near-frontier failure claim"}


def gds_figure():
    controls = [
        ("5T OTA", "phase0_20261018T232943675208Z_custom_ota_build", "five_t_ota.gds"),
        ("Compact Miller OTA", "phase0_20261018T234425820562Z_custom_ota_miller_build", "compact_miller_ota.gds"),
        ("Cascode mirror", "phase0_20261019T013627305579Z_independent_characterization", "cascode_mirror.gds"),
        ("Source follower", "phase0_20261019T013536890251Z_independent_characterization", "source_follower.gds"),
        ("Stacked switch", "phase0_20261019T013451038491Z_stacked_switch_probe", "stacked_switch.gds"),
        ("Common-source stage", "phase0_20261019T013958865534Z_common_source_probe", "common_source_stage.gds"),
        ("Resistively loaded pair", "phase0_20261019T014137569946Z_resistive_diff_probe", "resistive_diff.gds")]
    layers = [(65, "#7ca9a0", "Active"), (66, "#bf7275", "Poly"),
        (68, "#638abd", "M1"), (69, "#b69062", "M2"), (70, "#bf79b0", "M3"),
        (71, "#72aa76", "M4"), (72, "#b8a654", "M5")]
    figure, axes = plt.subplots(2, 4, figsize=(10, 5.3))
    provenance = []
    for axis, (title, run, filename) in zip(axes.flat, controls):
        path = RAW / run / filename
        library = gdstk.read_gds(path)
        top, = library.top_level()
        box = top.bounding_box()
        for layer, color, label in layers:
            polygons = top.get_polygons(layer=layer, datatype=20)
            axis.add_collection(PolyCollection([p.points for p in polygons], facecolors=color, edgecolors="none", alpha=.7, rasterized=True))
        width, height = np.diff(box, axis=0)[0]
        axis.set(xlim=(box[0][0]-1, box[1][0]+1), ylim=(box[0][1]-1, box[1][1]+1), aspect="equal")
        axis.set_title(title + "\n" + f"{width:.1f} × {height:.1f} µm", fontsize=8)
        axis.set_xticks([]); axis.set_yticks([])
        for spine in axis.spines.values():spine.set_visible(False)
        provenance.append({"label": title, "actual_gds": str(path.relative_to(ROOT)), "top_cell": top.name,
            "bbox_um": np.asarray(box).tolist(), "scale": "Each panel fits its actual extent; panels do not share scale"})
    axes.flat[-1].axis("off")
    axes.flat[-1].legend(handles=[Patch(facecolor=color, label=label) for _,color,label in layers], loc="center", ncol=2, frameon=False, fontsize=8)
    figure.suptitle("Actual generated GDS — development controls", fontsize=11)
    figure.tight_layout(rect=(0, 0, 1, .95), h_pad=1.2)
    save(figure, "development_generator_gds")
    return provenance


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8, "axes.titlesize": 9, "pdf.fonttype": 42, "ps.fonttype": 42})
    metadata = {"fidelity_figure": pool_figure(), "GDS_panels": gds_figure(), "formal_experiment_results": False}
    (OUT / "development_figure_sources.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps({"output": str(OUT), "figures": 2, "actual_GDS_panels": len(metadata["GDS_panels"])}))
