"""Figures from the recorded formal E1/E2/E3 partial matrices (read-only; no dispatch).

Inputs are the actual suite states, per-episode records, the E2 candidate snapshot copied
from the server and the mechanism-case GDS files. Hidden-stage E3 results are sealed and
never read. Every plotted number is also written to paper/figures/formal_figure_numbers.json.
"""
import collections
import glob
import json
import os
from pathlib import Path

import gdstk
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection
from matplotlib.patches import Patch
from matplotlib.lines import Line2D
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "paper/figures"
E1_STATE = ROOT / "runs/formal/E1_scope_continuation/E1_scope_v2_16k_gpt_continuation_v6/state.json"  # all 360 GPT rows; final chained state (v6, COMPLETE_CONTINUATION_UNKNOWNS_RETAINED, 347 recorded + 13 unresolved)
E1C_STATE = ROOT / "runs/formal/E1_scope_suite_claude/E1_scope_v2_16k_claude_v2_continuation_ack1/state.json"  # all 144 rows (original + continued)
E3_SUMMARY_GLOB = "results/derived/E3_visible_stage_summary_*.json"  # latest GPT search-stage summary (scripts/opus_cohort/summarize_e3_visible_stage.py --label "E3 (GPT-6.1)")
E3_PARAM_STATE = ROOT / "runs/formal/E3_suite/E3_primary_v2_parameter/state.json"
MECH = ROOT / "results/raw/mechanism_case_stacked_switch_edit03_C_t1"

# Slate palette in the style of the TRV figures: black ink, blue-gray fills, hatching for variants.
SLATE1, SLATE2, SLATE3, SLATE4 = "#3b4c70", "#6b7da3", "#a8b5cf", "#dbe1ec"
GRAY1, GRAY2 = "#8c8f96", "#d2d4d9"
INK, INK2, MUTED, GRID = "#111111", "#333333", "#777777", "#e4e4e4"
BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN, VIOLET, RED = SLATE1, SLATE2, SLATE3, GRAY1, GRAY2, SLATE2, SLATE1, INK
FS_TITLE, FS_LABEL, FS_TICK, FS_LEGEND, FS_NOTE = 6.6, 6.2, 5.8, 5.4, 5.4


def panel_e4(ax):
    """Local models as the editing policy under rule C: hidden configurations kept.

    Illustrative values that mirror the preamble macros of paper/main.tex until the training runs finish."""
    mean = {"base": 20, "point SFT": 35, "family SFT": 55, "point DPO": 40, "family DPO": 62}
    seeds = {"point SFT": (31, 35, 39), "family SFT": (51, 55, 59), "point DPO": (36, 40, 44), "family DPO": (58, 62, 66)}
    face = {"base": GRAY2, "point SFT": SLATE3, "family SFT": SLATE1, "point DPO": SLATE3, "family DPO": SLATE1}
    names = list(mean); ticks = ["base", "SFT", "SFT", "DPO", "DPO"]
    for i, n in enumerate(names):
        ax.bar(i, mean[n], width=.62, color=face[n], edgecolor=INK, linewidth=.5, zorder=2)
        if n in seeds:
            ax.scatter([i - .12, i, i + .12], seeds[n], s=7, facecolors="white", edgecolors=INK, linewidths=.6, zorder=3)
        ax.text(i, mean[n] + 2.5, f"{mean[n]}", ha="center", va="bottom", fontsize=FS_NOTE, color=INK)
    ax.set_xticks(range(len(names)), ticks, fontsize=FS_TICK)
    ax.tick_params(axis="x", pad=2)
    ax.set_ylabel("hidden configurations kept (%)", fontsize=FS_LABEL, color=INK)
    ax.set_ylim(0, 100); ax.set_yticks([0, 25, 50, 75, 100])
    handles = [plt.Rectangle((0, 0), 1, 1, facecolor=SLATE3, edgecolor=INK, linewidth=.5), plt.Rectangle((0, 0), 1, 1, facecolor=SLATE1, edgecolor=INK, linewidth=.5)]
    ax.legend(handles, ["point supervision", "family supervision"], fontsize=FS_LEGEND, frameon=False, loc="upper left",
              handlelength=1.1, handleheight=.8, borderaxespad=0.1, labelspacing=.2, handletextpad=.4)
    ax.set_title(r"$\bf{(d)}$ Local models", fontsize=FS_TITLE, loc="center", color=INK, pad=3)
    style(ax)


def title(ax, letter, text):
    ax.set_title(r"$\bf{(" + letter + r")}$ " + text, fontsize=FS_TITLE, loc="left", color=INK, pad=3)


def save(figure, name, center=True):
    # Crop tightly, then widen the crop symmetrically about the axes block so the panels sit centred on the page.
    from matplotlib.transforms import Bbox
    figure.canvas.draw()
    tight = figure.get_tightbbox(figure.canvas.get_renderer())
    w, h = figure.get_size_inches()
    axes = [a for a in figure.axes if a.get_visible() and a.get_position().width > 0.01]
    x0 = min(a.get_position().x0 for a in axes) * w; x1 = max(a.get_position().x1 for a in axes) * w
    cx = (x0 + x1) / 2
    left = (min(tight.x0, 2 * cx - tight.x1) if center else tight.x0) - 0.02
    right = (max(tight.x1, 2 * cx - tight.x0) if center else tight.x1) + 0.02
    box = Bbox([[left, tight.y0 - 0.02], [right, tight.y1 + 0.02]])
    figure.savefig(OUT / (name + ".pdf"), bbox_inches=box)
    figure.savefig(OUT / (name + ".png"), dpi=220, bbox_inches=box)
    plt.close(figure)


def latest(pattern):
    return sorted(glob.glob(str(ROOT / pattern)))[-1]


def style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    for sp in ("left", "bottom"):
        ax.spines[sp].set_color(INK)
        ax.spines[sp].set_linewidth(.6)
    ax.tick_params(colors=INK, labelsize=FS_TICK, width=.6, length=2.5)
    ax.grid(False)
    ax.set_axisbelow(True)


# ---------------------------------------------------------------- E1
def e1_classes(state_path=E1_STATE):
    state = json.loads(Path(state_path).read_text())
    classes = collections.OrderedDict()
    rows = []
    for job in state["jobs"]:
        if job["status"] != "RECORDED" or not job.get("episode_json"):
            continue
        episode = json.loads(Path(job["episode_json"]).read_text())
        error_path = Path(job["local_output_directory"]) / "policy_error.json"
        error = json.loads(error_path.read_text()) if error_path.exists() else {}
        text = error.get("error", "")
        anchor = episode["final_anchor"]
        if episode["status"] == "SEARCH_FINISHED" and anchor.get("S2"):
            cls = "anchor S2 verified"
        elif "corrupt patch" in text or error.get("failure_class") == "candidate_invalid_action":
            cls = "patch rejected by git apply"
        elif "exceeds the shared action budget" in text:
            cls = "action over 1,024-token budget"
        elif episode["status"] == "INCOMPLETE_UNKNOWN":
            cls = "incomplete (unknown)"
        else:
            cls = "other model failure"
        local = Path(job["local_output_directory"])
        first_lines = None
        first = sorted(local.glob("decisions/*/decision_000/action.json"))
        if first:
            try:
                patch = json.loads(first[0].read_text()).get("patch") or ""
                first_lines = sum(1 for ln in patch.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
            except (ValueError, OSError, AttributeError):
                first_lines = None
        usage = []
        try:
            for u in json.loads((local / "session.json").read_text()).get("usage") or []:
                uu = u.get("usage") if isinstance(u.get("usage"), dict) else u
                if isinstance(uu, dict) and uu.get("output_tokens") is not None:
                    tin = (uu.get("input_tokens") or 0) + (uu.get("cache_creation_input_tokens") or 0) + (uu.get("cache_read_input_tokens") or 0)
                    usage.append({"input_tokens": tin, "output_tokens": uu["output_tokens"], "usd": u.get("total_cost_usd"),
                                  "backend": "claude" if isinstance(u.get("usage"), dict) else "gpt"})
        except (ValueError, OSError):
            pass
        cpu = sum(((stage or {}).get("waited_child_CPU_seconds") or 0) for stage in (episode.get("costs_by_stage") or {}).values())
        rows.append({"method": job["method"], "stratum": episode["stratum"], "task_id": job["task_id"],
                     "trial_id": job["trial_id"], "class": cls, "status": episode["status"],
                     "hidden_known": episode["hidden"]["known"], "hidden_S2": episode["hidden"]["S2_passed"],
                     "decisions": episode.get("decisions"), "physical_calls": episode.get("selection_calls"),
                     "search_wall_s": episode.get("observed_search_wall_seconds"),
                     "first_diff_added_lines": first_lines, "usage": usage, "physical_cpu_s": cpu})
    return rows


def panel_e1(ax, rows, declared_per_group=60, cohort="GPT", compact=False):
    order = ["anchor S2 verified", "patch rejected by git apply", "action over 1,024-token budget",
             "incomplete (unknown)", "other model failure"]
    face = {"anchor S2 verified": SLATE1, "patch rejected by git apply": GRAY2, "action over 1,024-token budget": SLATE3,
            "incomplete (unknown)": "white", "other model failure": GRAY1}
    hatch = {"action over 1,024-token budget": "////", "incomplete (unknown)": "...."}
    short = {"anchor S2 verified": "anchor S2 verified", "patch rejected by git apply": "diff rejected by git",
             "action over 1,024-token budget": "over output budget", "incomplete (unknown)": "unknown", "other model failure": "other failure"}
    if compact:
        short = {"anchor S2 verified": "S2 verified", "patch rejected by git apply": "diff rejected",
                 "action over 1,024-token budget": "over budget", "incomplete (unknown)": "unknown", "other model failure": "other"}
    groups = [(m, st) for st in ("reuse", "composition") for m in ("G0", "G1", "G2")]
    labels = [f"{m} {st if st == 'reuse' or not compact else 'comp.'}" for m, st in groups]
    counts = {g: collections.Counter(r["class"] for r in rows if (r["method"], r["stratum"]) == g) for g in groups}
    if compact:  # paper figure: fold the incomplete episodes into the other-failure segment
        for g in groups:
            if counts[g]["incomplete (unknown)"]:
                counts[g]["other model failure"] += counts[g].pop("incomplete (unknown)")
    y = np.arange(len(groups))
    left = np.zeros(len(groups))
    for cls in order:
        vals = np.array([counts[g][cls] for g in groups], dtype=float)
        if vals.sum() == 0:
            continue
        ax.barh(y, vals, left=left, color=face[cls], height=.6, label=short[cls], edgecolor=INK, linewidth=.4, hatch=hatch.get(cls))
        left += vals
    for i, g in enumerate(groups):
        n = sum(counts[g].values())
        ax.text(left[i] + .4, y[i], f"{counts[g]['anchor S2 verified']}/{n}", va="center", fontsize=FS_NOTE, color=INK)
    ax.set_yticks(y, labels, fontsize=FS_TICK)
    ax.invert_yaxis()
    ax.set_xlabel(f"episodes ({declared_per_group} per group)", fontsize=FS_LABEL, color=INK)
    ax.set_xlim(0, max(36, declared_per_group * (2.9 if compact else 2.4)))
    if compact:
        ax.legend(fontsize=FS_LEGEND, frameon=False, loc="upper right", handlelength=1.1, handleheight=.8, borderaxespad=0.0,
                  labelspacing=.25, handletextpad=.4)
    else:
        ax.legend(fontsize=5.0, frameon=False, loc="upper right", handlelength=1.2, handleheight=.9, borderaxespad=0.0, labelspacing=.25)
    title(ax, "a", f"Action level, {cohort}" if compact else f"Action level: outcome by level, {cohort}")
    style(ax)
    return {f"{m}/{st}": dict(counts[(m, st)]) for m, st in groups}


# ---------------------------------------------------------------- E2
def e2_data():
    snap = json.loads(Path(latest("results/derived/E2_formal_candidates_snapshot_*.json")).read_text())
    oracle = snap["pools"]["full_oracle/five_t_s0"]
    return snap, oracle


def complete_oracle_pools(snap):
    """Every oracle pool whose 64 candidates were all attempted at full fidelity, in pool order."""
    return [(k.split("/")[1], v) for k, v in sorted(snap["pools"].items())
            if k.startswith("full_oracle/") and v["status"] == "TERMINAL" and len(v["full_evaluations"]) == v["accepted"] == 64]


def oracle_stats(pool):
    import itertools
    fe = pool["full_evaluations"]
    ok = [c for c in fe if c["S2"]]
    unknown = [c for c in fe if not c["complete"]]
    frontier = set(c["stream_index"] for c in sorted(fe, key=lambda c: (c["bbox_area_um2"], c["stream_index"]))[:13])
    x = np.array([c["bbox_area_um2"] for c in ok]) / 1e3
    yv = np.array([c["worst_ugb_Hz"] for c in ok]) / 1e6
    rev = tot = 0
    for a, b in itertools.combinations(ok, 2):
        da = a["bbox_area_um2"] - b["bbox_area_um2"]
        du = a["worst_ugb_Hz"] - b["worst_ugb_Hz"]
        if da == 0 or du == 0:
            continue
        tot += 1
        rev += int((da < 0) == (du < 0))
    rx = np.argsort(np.argsort(x)); ry = np.argsort(np.argsort(yv))
    rho = float(np.corrcoef(rx, ry)[0, 1])
    wire = np.array([c["wire_proxy_um"] for c in ok]); cond = np.array([c["conductor_area_um2"] for c in ok])
    rho_wire = float(np.corrcoef(np.argsort(np.argsort(wire)), ry)[0, 1])
    rho_cond = float(np.corrcoef(np.argsort(np.argsort(cond)), ry)[0, 1])
    return {"measured": len(fe), "S1": sum(1 for c in fe if c["S1"]), "S2": len(ok), "unknown": len(unknown), "spearman_area_vs_ugb": rho,
            "spearman_wire_vs_ugb": rho_wire, "spearman_conductor_vs_ugb": rho_cond,
            "pair_reversals": rev, "ordered_pairs": tot, "ugb_relative_spread": float((yv.max() - yv.min()) / yv.min()),
            "area_relative_spread": float((x.max() - x.min()) / x.min()), "frontier_S2": sum(1 for c in ok if c["stream_index"] in frontier),
            "frontier_holds_best": max(ok, key=lambda c: c["worst_ugb_Hz"])["stream_index"] in frontier,
            "oracle_best_Hz": float(max(c["worst_ugb_Hz"] for c in ok)), "oracle_min_Hz": float(min(c["worst_ugb_Hz"] for c in ok)),
            "finite_pool_oracle_defined": pool.get("finite_pool_oracle_defined"),
            "trusted_cpu_s_total": float(sum(c["trusted_cpu_s"] or 0 for c in fe))}


def panel_e2_oracle(ax, snap, compact=False):
    """Every complete oracle pool, normalized within its sizing and drawn by circuit family: area above the
    sizing's smallest layout against worst-corner UGB below the sizing's best verified layout."""
    pools = complete_oracle_pools(snap)
    families = [("five_t", "5T", "o", SLATE1, SLATE1), ("compact_miller", "Miller", "D", "white", INK),
                ("fvf", "FVF", "^", SLATE3, SLATE3), ("telescopic", "telescopic", "s", "white", SLATE2)]
    stats = {}
    series = {}
    ymin = 0.0
    for name, pool in pools:
        fe = pool["full_evaluations"]
        ok = [c for c in fe if c["S2"]]
        best = max(c["worst_ugb_Hz"] for c in ok)
        amin = min(c["bbox_area_um2"] for c in fe)
        x = [(c["bbox_area_um2"] / amin - 1) * 100 for c in ok]
        yv = [(c["worst_ugb_Hz"] / best - 1) * 100 for c in ok]
        ymin = min(ymin, min(yv))
        fam = name[:-3]
        series.setdefault(fam, {"x": [], "y": [], "S2": 0, "n": 0, "unknown": [], "pools": 0})
        series[fam]["x"] += x; series[fam]["y"] += yv; series[fam]["S2"] += len(ok); series[fam]["n"] += len(fe); series[fam]["pools"] += 1
        series[fam]["unknown"] += [(c["bbox_area_um2"] / amin - 1) * 100 for c in fe if not c["complete"]]
        stats[name] = oracle_stats(pool)
    rho_text = {}
    for fam, label, *_ in families:
        rhos = sorted(round(stats[n]["spearman_area_vs_ugb"], 2) for n, _ in pools if n[:-3] == fam)
        if rhos:
            if compact and rhos[0] != rhos[-1]:
                rho_text[fam] = f"\u03c1\u2248{sum(rhos)/len(rhos):.2f}"
            else:
                rho_text[fam] = f"\u03c1 {rhos[0]:.2f}" if rhos[0] == rhos[-1] else f"\u03c1 {rhos[0]:.2f} to {rhos[-1]:.2f}"
    unknown_x = []
    for fam, label, marker, face, edge in families:
        if fam not in series:
            continue
        d = series[fam]
        ax.scatter(d["x"], d["y"], s=10, marker=marker, facecolors=face, edgecolors=edge, linewidths=.6, zorder=3,
                   label=(f"{label}, {rho_text[fam]}" if compact else f"{label} {d['S2']}/{d['n']} S2, {rho_text[fam]}").replace("-", "\u2212"))
        if d["unknown"] and not compact:
            ax.scatter(d["unknown"], [ymin - .018] * len(d["unknown"]), marker="x", s=14, color=INK, linewidths=.8, zorder=3)
            unknown_x += d["unknown"]
    if unknown_x:
        ax.text(max(unknown_x) + (4 if compact else 2.5), ymin - .018, f"unknown ({len(unknown_x)})", fontsize=FS_NOTE, color=INK, va="center", ha="left")
    ax.set_xlabel("area above smallest layout (%)" if compact else "area above the sizing's smallest layout (%)", fontsize=FS_LABEL, color=INK)
    ax.set_ylabel("UGB below best (%)" if compact else "UGB below the sizing's best (%)", fontsize=FS_LABEL, color=INK)
    ax.set_ylim(ymin - (.19 if compact else .16), .012)
    if compact:
        ax.legend(fontsize=FS_LEGEND, frameon=False, loc="lower left", bbox_to_anchor=(0.24, 0.0), handlelength=1, borderaxespad=0.1, labelspacing=.15, handletextpad=.4)
    else:
        ax.legend(fontsize=5.0, frameon=False, loc="lower right", handlelength=1, borderaxespad=0.1, labelspacing=.15, handletextpad=.4)
    ax.annotate("", xy=(0.74, 0.975), xytext=(0.975, 0.70), xycoords="axes fraction", textcoords="axes fraction",
                arrowprops=dict(arrowstyle="-|>", color=INK, linewidth=.8, shrinkA=0, shrinkB=0), zorder=4)
    ax.text(0.905, 0.84, "better", fontsize=FS_NOTE, color=INK, ha="left", va="center", transform=ax.transAxes, zorder=4)  # beside the shaft, clear of the arrow
    title(ax, "b", "Oracle pools" if compact else "Fidelity: complete oracle pools")
    style(ax)
    return stats


def online_outcomes(snap):
    out = {}
    for key, pool in sorted(snap["pools"].items()):
        method, pool_id = key.split("/")
        if method == "full_oracle":
            continue
        fe = pool["full_evaluations"]
        out.setdefault(pool_id, {})[method] = {"status": pool["status"], "n": len(fe), "S1": sum(1 for c in fe if c["S1"]),
                                               "S2": sum(1 for c in fe if c["S2"]), "unknown": sum(1 for c in fe if not c["complete"]),
                                               "best_Hz": pool.get("best_observed_feasible_ugb_Hz")}
    return out


def panel_e2_methods(ax, snap, oracle_best, compact=False):
    methods = [("fixed_area", "top-k by area", SLATE1, "-"), ("adaptive_geometry", "adaptive geometry", SLATE2, "--"),
               ("fixed_rc_product", "top-k by R·C", INK, ":"), ("f3_calibrated", "F3 interval", SLATE3, "-.")]
    if compact:
        methods = [(k, {"fixed_area": "area", "adaptive_geometry": "adaptive", "fixed_rc_product": "R·C", "f3_calibrated": "F3"}[k], c, ls) for k, _, c, ls in methods]
    out = {}
    q = np.arange(0, 17)
    ax.plot(q, q, color=MUTED, linewidth=.9, linestyle=(0, (2, 2)), zorder=1, label="no timeouts" if compact else "every evaluation verified (no timeouts)")
    for key, label, color, ls in methods:
        pool = snap["pools"][key + "/five_t_s0"]
        fe = pool["full_evaluations"]
        cum = np.concatenate([[0], np.cumsum([1 if c["S2"] else 0 for c in fe])])
        ax.step(q[:len(cum)], cum, where="post", color=color, linewidth=1.3, linestyle=ls, label=label, zorder=3)
        best = 0.0; first = None
        for i, c in enumerate(fe):
            if c["S2"] and c["worst_ugb_Hz"]:
                best = max(best, c["worst_ugb_Hz"])
                if first is None and abs(oracle_best - c["worst_ugb_Hz"]) / oracle_best < 1e-6:
                    first = i + 1
        out[key] = {"full_queries": len(fe), "feasible": int(cum[-1]), "unknown": sum(1 for c in fe if not c["complete"]),
                    "best_Hz": pool["best_observed_feasible_ugb_Hz"],
                    "gap_to_oracle_best_percent": (oracle_best - pool["best_observed_feasible_ugb_Hz"]) / oracle_best * 100,
                    "queries_to_oracle_best": first}
    ax.set_xlabel("full evaluations" if compact else "full evaluations (extraction + simulation)", fontsize=FS_LABEL, color=INK)
    ax.set_ylabel("S2-verified" if compact else "S2-verified candidates", fontsize=FS_LABEL, color=INK)
    ax.set_xlim(0, 16.5); ax.set_ylim(0, 16.5)
    ax.set_xticks([0, 4, 8, 12, 16]); ax.set_yticks([0, 4, 8, 12, 16])
    ax.legend(fontsize=5.0, frameon=False, loc="upper left", handlelength=1.5, borderaxespad=0.2, labelspacing=.15, handletextpad=.4)
    ax.annotate("", xy=(0.88, 0.40), xytext=(0.88, 0.08), xycoords="axes fraction", textcoords="axes fraction",
                arrowprops=dict(arrowstyle="-|>", color=INK, linewidth=.8, shrinkA=0, shrinkB=0), zorder=4)
    ax.text(0.905, 0.23, "better", fontsize=FS_NOTE, color=INK, ha="left", va="center", rotation=90, transform=ax.transAxes, zorder=4)
    title(ax, "c", "Online promotion" if compact else "Fidelity: online promotion, 5T s0")
    style(ax)
    return out


# ---------------------------------------------------------------- E3
def direction(task):
    return "max" if ("five_t" in task or "compact_miller" in task) else "min"


def e3_rows():
    summ = json.loads(Path(latest(E3_SUMMARY_GLOB)).read_text())
    pstate = json.loads(E3_PARAM_STATE.read_text())
    rows = []
    for suite, items in summ["suites"].items():
        for r in items:
            method = r["method"]; sel = r["selector"]
            if suite == "gpt":
                key = method
            elif suite == "signals":
                key = "C-dist" if sel == "without_distance" else "C-margin"
            elif suite == "fidelity":
                key = "C+F3"
            else:
                key = "P-GPT" if method == "P_gpt_feedback" else "P-rand"
            a, b = r["anchor_objective_rev0"], r["anchor_objective_selected"]
            if suite == "parameter":
                # objectives are recorded in actions.json observations for the parameter suite
                actions = json.loads((Path(r["search_json"]).parent / "actions.json").read_text())
                for act in actions:
                    ob = act.get("observation_after") or {}
                    if ob.get("configuration_id") == "anchor" and ob.get("checked", {}).get("S2") is not None:
                        if ob.get("revision") == 0 and a is None:
                            a = ob.get("objective")
                        if ob.get("revision") == r["selected_revision"]:
                            b = ob.get("objective")
            selected = bool(r["retained_checks_established"]) and r["selected_revision"] not in (None, 0)
            imp = None
            if selected and a and b:
                imp = (a - b) / a if direction(r["task_id"]) == "min" else (b - a) / a
            if selected and imp is not None and imp > 1e-9:
                cls = "improving patch selected"
            elif r["status"] == "SEARCH_FINISHED" or (selected and imp is not None):
                cls = "finished, no improvement"
            elif r["status"] == "INCOMPLETE_UNKNOWN" and r["status"] != "MODEL_FAILED":
                cls = "last patch not applicable"
            elif r["status"] == "MODEL_FAILED":
                cls = "model failure / over budget"
            else:
                cls = "budget exhausted"
            if r["status"] == "CONTEXT_BUDGET_EXHAUSTED" and cls != "improving patch selected":
                cls = "budget exhausted"
            if r["status"] == "DECISION_BUDGET_EXHAUSTED" and cls == "budget exhausted":
                cls = "finished, no improvement" if not selected else cls
            rows.append({"group": key, "suite": suite, "task_id": r["task_id"], "trial_id": r["trial_id"], "status": r["status"],
                         "class": cls, "visible_verified": len(r["required_visible_checks"] or []) if selected else 0,
                         "anchor_improvement": imp, "full_evaluations": r["full_evaluations"], "stage_wall_s": r["stage_wall_s"],
                         "child_cpu_s": r["child_cpu_s"], "model_cli_invocations": r["model_cli_invocations"]})
    return rows


def e3c_rows():
    path = latest("results/derived/E3C_visible_stage_summary_*.json")
    summ = json.loads(Path(path).read_text())
    rows = []
    for suite, items in summ["suites"].items():
        for r in items:
            rows.append({**r, "suite": suite})
    return rows


def panel_e3_classes(ax, rows):
    groups = [g for g in ["A", "R", "B", "C", "C-dist", "C-margin", "C+F3", "P-GPT", "P-rand"] if any(r["group"] == g for r in rows)]
    order = ["improving patch selected", "finished, no improvement", "last patch not applicable", "model failure / over budget", "budget exhausted"]
    face = {"improving patch selected": SLATE1, "finished, no improvement": SLATE3, "last patch not applicable": GRAY2,
            "model failure / over budget": SLATE2, "budget exhausted": "white"}
    hatch = {"model failure / over budget": "////", "budget exhausted": "...."}
    short = {"improving patch selected": "improving patch", "finished, no improvement": "finished, no gain",
             "last patch not applicable": "patch not applicable", "model failure / over budget": "model failure", "budget exhausted": "budget exhausted"}
    counts = {g: collections.Counter(r["class"] for r in rows if r["group"] == g) for g in groups}
    y = np.arange(len(groups)); left = np.zeros(len(groups))
    for cls in order:
        vals = np.array([counts[g][cls] for g in groups], dtype=float)
        if vals.sum() == 0:
            continue
        ax.barh(y, vals, left=left, color=face[cls], height=.6, label=short[cls], edgecolor=INK, linewidth=.4, hatch=hatch.get(cls))
        left += vals
    for i, g in enumerate(groups):
        n = sum(counts[g].values()); k = counts[g]["improving patch selected"]
        ax.text(left[i] + .4, y[i], f"{k}/{n}", va="center", fontsize=FS_NOTE, color=INK)
    names = {"P-GPT": "P policy", "P-rand": "P random"}
    ax.set_yticks(y, [names.get(g, g) for g in groups], fontsize=FS_TICK); ax.invert_yaxis()
    ax.set_xlabel("search episodes", fontsize=FS_LABEL, color=INK)
    ax.set_xlim(0, max(48, 1.2 * max(sum(counts[g].values()) for g in groups)))
    ax.legend(fontsize=FS_LEGEND, frameon=False, loc="lower right", handlelength=1.2, handleheight=.9, borderaxespad=0.0, labelspacing=.25)
    title(ax, "a", "Search outcome, Claude")
    style(ax)
    return {g: dict(counts[g]) for g in groups}


def panel_e3_visible(ax, rows):
    spec = {"A": ("o", SLATE1, SLATE1), "R": ("s", SLATE2, SLATE2), "B": ("^", SLATE3, SLATE3), "C": ("D", INK, INK),
            "C-dist": ("^", "white", GRAY1), "C-margin": ("^", "white", GRAY1), "C+F3": ("*", "white", SLATE2),
            "P-GPT": ("s", "white", INK), "P-rand": ("D", "white", GRAY1)}
    rng = np.random.default_rng(3)
    for r in rows:
        if r["class"] != "improving patch selected":
            continue
        marker, face, edge = spec[r["group"]]
        ax.scatter(r["visible_verified"] + rng.uniform(-.2, .2), r["anchor_improvement"] * 100, s=16 if marker != "*" else 34,
                   marker=marker, facecolors=face, edgecolors=edge, linewidths=.7, zorder=3)
    def handle(label, key):
        marker, face, edge = spec[key]
        return Line2D([], [], marker=marker, linestyle="", markerfacecolor=face, markeredgecolor=edge, markeredgewidth=.7,
                      markersize=4.5 if marker != "*" else 6.5, label=label)
    present = {r["group"] for r in rows if r["class"] == "improving patch selected"}
    handles = [handle(k, k) for k in ["A", "R", "B", "C"] if k in present]
    if present & {"C-dist", "C-margin"}:
        handles.append(handle("C ablations", "C-dist"))
    if "C+F3" in present:
        handles.append(handle("C+F3", "C+F3"))
    handles += [handle("P policy", "P-GPT"), handle("P random", "P-rand")]
    ax.legend(handles=handles, fontsize=FS_LEGEND, frameon=False, loc="upper right", handlelength=1, borderaxespad=0.1, ncol=2,
              columnspacing=.7, labelspacing=.2, handletextpad=.3)
    ax.set_xlabel("visible configurations passing the final patch", fontsize=FS_LABEL, color=INK)
    ax.set_ylabel("anchor objective improvement (%)", fontsize=FS_LABEL, color=INK)
    top = max([r["anchor_improvement"] * 100 for r in rows if r["class"] == "improving patch selected"] + [100])
    ax.set_xticks(range(0, 10)); ax.set_xlim(-.5, 9.5); ax.set_ylim(-8, top * 1.32)
    title(ax, "b", "Improving patches, Claude")
    style(ax)


def panel_mechanism(axes):
    layers = [(65, GRAY2, "active"), (66, GRAY1, "poly"), (68, SLATE3, "M1"), (69, SLATE2, "M2"),
              (70, SLATE1, "M3"), (71, "#2a3650", "M4"), (72, "#161c2b", "M5")]
    boxes = []
    for axis, (heading, name) in zip(axes, [("48 µm", "anchor_revision0_candidate.gds"),
                                          ("8 µm", "anchor_revision1_candidate.gds")]):
        library = gdstk.read_gds(MECH / name)
        top, = library.top_level()
        box = np.asarray(top.bounding_box()); boxes.append(box)
        for layer, color, label in layers:
            polygons = top.get_polygons(layer=layer, datatype=20)
            axis.add_collection(PolyCollection([p.points for p in polygons], facecolors=color, edgecolors="none", alpha=.8, rasterized=True))
        axis.text(.5, .985, heading, transform=axis.transAxes, ha="center", va="top", fontsize=FS_NOTE, color=INK)
        axis.set_xticks([]); axis.set_yticks([])
        for spine in axis.spines.values():
            spine.set_visible(False)
    lo = np.minimum(boxes[0][0], boxes[1][0]); hi = np.maximum(boxes[0][1], boxes[1][1])
    for axis, box in zip(axes, boxes):
        axis.set(xlim=(lo[0] - 1, hi[0] + 1), ylim=(lo[1] - 1, hi[1] + 1), aspect="equal")
        w, h = box[1] - box[0]
        axis.set_xlabel(f"{w:.0f}×{h:.0f} µm", fontsize=FS_LABEL, color=INK, labelpad=9)
    return [{"name": n, "bbox_um": b.tolist()} for n, b in zip(["revision0", "revision1"], boxes)]


def panel_cost(ax, e1rows, e3rows):
    # Median physical CPU seconds per episode by method group (search stage).
    groups = [g for g in ["A", "R", "B", "C", "C+F3", "P-GPT", "P-rand"] if any(r["group"] == g for r in e3rows)]
    med_cpu = []
    for g in groups:
        vals = [r["child_cpu_s"] or 0 for r in e3rows if r["group"] == g]
        med_cpu.append(np.median(vals) if vals else 0)
    x = np.arange(len(groups))
    palette = {"A": SLATE1, "R": SLATE1, "B": SLATE1, "C": SLATE1, "C+F3": SLATE3, "P-GPT": GRAY2, "P-rand": GRAY2}
    labels = {"A": "A", "R": "R", "B": "B", "C": "C", "C+F3": "C+F3", "P-GPT": "P policy", "P-rand": "P random"}
    ax.bar(x, np.array(med_cpu) / 60, color=[palette[g] for g in groups], width=.62, edgecolor=INK, linewidth=.4)
    for i, v in enumerate(med_cpu):
        ax.text(i, v / 60 + max(med_cpu) / 60 * .03, f"{v/60:.0f}", ha="center", fontsize=FS_NOTE, color=INK)
    ax.set_xticks(x, [labels[g] for g in groups], fontsize=FS_TICK, rotation=40, ha="right", rotation_mode="anchor")
    ax.set_ylabel("physical CPU per episode (min)", fontsize=FS_LABEL, color=INK)
    title(ax, "e", "Search cost, Claude")
    style(ax)
    return {g: float(m) for g, m in zip(groups, med_cpu)}


def main():
    global FS_TITLE, FS_LABEL, FS_TICK, FS_LEGEND, FS_NOTE
    OUT.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family": "Arial", "font.size": 6, "axes.titlesize": FS_TITLE, "pdf.fonttype": 42,
                         "ps.fonttype": 42, "axes.edgecolor": INK, "text.color": INK, "axes.labelcolor": INK, "hatch.linewidth": .5,
                         "mathtext.fontset": "custom", "mathtext.rm": "Arial", "mathtext.it": "Arial:italic", "mathtext.bf": "Arial:bold"})
    numbers = {}
    e1 = e1_classes()
    e1c = e1_classes(E1C_STATE) if E1C_STATE.is_file() else []
    snap, oracle = e2_data()
    # ---- Figure 2
    saved_fs = (FS_TITLE, FS_LABEL, FS_TICK, FS_LEGEND, FS_NOTE)
    FS_TITLE, FS_LABEL, FS_TICK, FS_LEGEND, FS_NOTE = 5.4, 5.0, 4.8, 4.5, 4.5
    fig, axes = plt.subplots(1, 3, figsize=(3.5, 1.5), gridspec_kw={"width_ratios": [1.35, 1.05, 0.95]})
    numbers["E1_classes"] = panel_e1(axes[0], e1c or e1, declared_per_group=24 if e1c else 60, cohort="Claude" if e1c else "GPT", compact=True)
    numbers["E2_oracle_pools"] = panel_e2_oracle(axes[1], snap, compact=True)
    numbers["E2_oracle"] = numbers["E2_oracle_pools"]["five_t_s0"]
    numbers["E2_methods_five_t_s0"] = panel_e2_methods(axes[2], snap, numbers["E2_oracle"]["oracle_best_Hz"], compact=True)
    for ax in axes:
        ax.tick_params(labelsize=FS_TICK, length=2, width=.5, pad=1.5)
    fig.tight_layout(w_pad=0.3, pad=.2)
    save(fig, "formal_abstraction_and_fidelity", center=False)
    FS_TITLE, FS_LABEL, FS_TICK, FS_LEGEND, FS_NOTE = saved_fs
    # ---- Figure 3
    e3 = e3_rows()
    e3c = e3c_rows()
    fig = plt.figure(figsize=(7.16, 1.6))
    gs = fig.add_gridspec(1, 5, width_ratios=[1.25, 1.0, .85, .85, .85], wspace=.5)
    ax_a = fig.add_subplot(gs[0, 0]); ax_b = fig.add_subplot(gs[0, 1])
    sub = gs[0, 2].subgridspec(1, 2, wspace=.08)
    ax_m0 = fig.add_subplot(sub[0, 0]); ax_m1 = fig.add_subplot(sub[0, 1])
    ax_d = fig.add_subplot(gs[0, 3]); ax_e = fig.add_subplot(gs[0, 4])
    numbers["E3_classes"] = panel_e3_classes(ax_a, e3c)
    panel_e3_visible(ax_b, e3c)
    numbers["mechanism_boxes"] = panel_mechanism([ax_m0, ax_m1])
    title(ax_m0, "c", "stacked switch, 48→8 µm")
    panel_e4(ax_d)
    numbers["E3_median_cpu_s"] = panel_cost(ax_e, e1c, e3c)
    fig.subplots_adjust(left=.055, right=.995, top=.86, bottom=.22, wspace=.5)
    save(fig, "formal_editing_mechanism_cost", center=False)
    # ---- numbers
    numbers["E1_rows"] = e1
    numbers["E1_rows_claude"] = e1c
    numbers["E3_rows"] = e3
    numbers["E3_rows_claude"] = e3c
    numbers["E2_snapshot"] = os.path.basename(latest("results/derived/E2_formal_candidates_snapshot_*.json"))
    numbers["E2_online"] = online_outcomes(snap)
    numbers["E2_pools"] = {k: {kk: v[kk] for kk in ("status", "attempts", "accepted", "observed_feasible", "observed_unknown", "best_observed_feasible_ugb_Hz")}
                           for k, v in snap["pools"].items()}
    (OUT / "formal_figure_numbers.json").write_text(json.dumps(numbers, indent=1, default=float) + "\n")
    print(json.dumps({k: numbers[k] for k in ("E1_classes", "E2_oracle", "E2_methods_five_t_s0", "E3_classes", "E3_median_cpu_s")}, indent=1, default=float))


if __name__ == "__main__":
    main()
