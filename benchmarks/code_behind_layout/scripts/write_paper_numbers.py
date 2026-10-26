"""Emit paper/numbers.tex from machine-readable run records and derived files (read-only)."""
import collections
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NUM = json.loads((ROOT / "paper/figures/formal_figure_numbers.json").read_text())
E1 = NUM["E1_rows"]; E3 = NUM["E3_rows"]; E2O = NUM["E2_oracle"]; E2M = NUM["E2_methods_five_t_s0"]
macros = collections.OrderedDict()


def m(name, value):
    macros[name] = value


def med(values):
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


# ---------------- E1
m("EOneRecorded", len(E1))
SPELLED = {"G0": "GZero", "G1": "GOne", "G2": "GTwo"}
for meth in ("G0", "G1", "G2"):
    rows = [r for r in E1 if r["method"] == meth]
    tag = SPELLED[meth]
    m(f"EOne{tag}N", len(rows))
    m(f"EOne{tag}Corrupt", sum(1 for r in rows if r["class"] == "patch rejected by git apply"))
    m(f"EOne{tag}Over", sum(1 for r in rows if r["class"] == "action over 1,024-token budget"))
    for stratum in ("reuse", "composition"):
        sub = [r for r in rows if r["stratum"] == stratum]
        key = "Reuse" if stratum == "reuse" else "Comp"
        m(f"EOne{tag}{key}N", len(sub)); m(f"EOne{tag}{key}S", sum(1 for r in sub if r["class"] == "anchor S2 verified"))
succ = [r for r in E1 if r["class"] == "anchor S2 verified"]
m("EOneSuccessHiddenFull", sum(1 for r in succ if r["hidden_S2"] == 16 and r["hidden_known"] == 16))
m("EOneCorruptTotal", sum(1 for r in E1 if r["class"] == "patch rejected by git apply"))
m("EOneOverTotal", sum(1 for r in E1 if r["class"] == "action over 1,024-token budget"))
m("EOneUnknownTotal", sum(1 for r in E1 if r["class"] == "incomplete (unknown)"))


def e1_extras(rows, prefix):
    """Per-level first-diff size, output tokens per decision, composition totals, median decisions of G2 successes."""
    for meth in ("G0", "G1", "G2"):
        sub = [r for r in rows if r["method"] == meth]; tag = SPELLED[meth]
        lines = med([r.get("first_diff_added_lines") for r in sub])
        toks = [u["output_tokens"] for r in sub for u in (r.get("usage") or [])]
        m(f"{prefix}{tag}FirstDiffLines", f"{lines:.0f}" if lines is not None else "--")
        m(f"{prefix}{tag}OutTok", f"{statistics.median(toks):,.0f}" if toks else "--")
    comp = [r for r in rows if r["stratum"] == "composition"]
    m(f"{prefix}CompN", len(comp)); m(f"{prefix}CompS", sum(1 for r in comp if r["class"] == "anchor S2 verified"))
    g2 = med([r["decisions"] for r in rows if r["method"] == "G2" and r["class"] == "anchor S2 verified"])
    m(f"{prefix}GTwoMedianDecisions", f"{g2:g}" if g2 is not None else "--")
    # cost per verified configuration (anchor plus the hidden configurations it passed), by level
    for meth, tag in (("G0", "GZero"), ("G1", "GOne"), ("G2", "GTwo"), (("G0", "G1"), "Low")):
        sub = [r for r in rows if (r["method"] in meth if isinstance(meth, tuple) else r["method"] == meth)]
        tok = sum(u["output_tokens"] for r in sub for u in (r.get("usage") or []))
        cpu = sum(r.get("physical_cpu_s") or 0 for r in sub)
        ver = sum(1 + (r.get("hidden_S2") or 0) for r in sub if r["class"] == "anchor S2 verified")
        m(f"{prefix}{tag}TokPerVerifiedK", f"{tok/1000/ver:,.1f}" if ver else "--")
        m(f"{prefix}{tag}CpuPerVerifiedMin", f"{cpu/60/ver:,.0f}" if ver else "--")
        m(f"{prefix}{tag}VerifiedConfigs", ver); m(f"{prefix}{tag}OutTokTotalK", f"{tok/1000:,.0f}")
    def per_verified(meths):
        sub = [r for r in rows if r["method"] in meths]
        tok = sum(u["output_tokens"] for r in sub for u in (r.get("usage") or []))
        ver = sum(1 + (r.get("hidden_S2") or 0) for r in sub if r["class"] == "anchor S2 verified")
        return tok / ver if ver else None
    low, high = per_verified(("G0", "G1")), per_verified(("G2",))
    m(f"{prefix}LowToGTwoTokRatio", f"{low/high:.0f}" if low and high else "--")
    succ = [r for r in rows if r["class"] == "anchor S2 verified"]
    m(f"{prefix}SuccessTotal", len(succ))
    m(f"{prefix}HiddenUnknown", sum(1 for r in succ if r["hidden_known"] < 16))
    m(f"{prefix}HiddenFailed", sum(1 for r in succ if r["hidden_known"] == 16 and r["hidden_S2"] < 16))


e1_extras(E1, "EOne")
# ---------------- E2
m("ETwoMeasured", E2O["measured"]); m("ETwoSTwo", E2O["S2"]); m("ETwoUnknown", E2O["unknown"])
m("ETwoSpearman", f"{E2O['spearman_area_vs_ugb']:.2f}"); m("ETwoReversals", E2O["pair_reversals"]); m("ETwoPairs", E2O["ordered_pairs"])
m("ETwoUgbSpread", f"{E2O['ugb_relative_spread']*100:.2f}"); m("ETwoAreaSpread", f"{E2O['area_relative_spread']*100:.0f}")
m("ETwoFrontierSTwo", E2O["frontier_S2"]); m("ETwoOracleBestMHz", f"{E2O['oracle_best_Hz']/1e6:.3f}"); m("ETwoOracleMinMHz", f"{E2O['oracle_min_Hz']/1e6:.3f}")
for key, tag in (("fixed_area", "Area"), ("adaptive_geometry", "Adapt"), ("fixed_rc_product", "RC"), ("f3_calibrated", "FThree")):
    m(f"ETwo{tag}Feasible", E2M[key]["feasible"]); m(f"ETwo{tag}Unknown", E2M[key]["unknown"])
    m(f"ETwo{tag}Queries", E2M[key]["queries_to_oracle_best"] if E2M[key]["queries_to_oracle_best"] else "--")
m("ETwoAreaGap", f"{E2M['fixed_area']['gap_to_oracle_best_percent']:.3f}")
# per-sizing oracle pools (every complete 64-candidate five-transistor pool)
E2P = NUM.get("E2_oracle_pools", {})
SIZING = {"five_t_s0": "SZero", "five_t_s1": "SOne", "five_t_s2": "STwoS", "compact_miller_s0": "MillerSZero",
          "compact_miller_s1": "MillerSOne", "compact_miller_s2": "MillerSTwoS", "fvf_s0": "FvfSZero", "fvf_s1": "FvfSOne", "fvf_s2": "FvfSTwoS",
          "telescopic_s0": "TeleSZero", "telescopic_s1": "TeleSOne", "telescopic_s2": "TeleSTwoS"}
for pool, tag in SIZING.items():
    if pool not in E2P:
        continue
    st = E2P[pool]
    m(f"ETwo{tag}STwo", st["S2"]); m(f"ETwo{tag}Unknown", st["unknown"])
    m(f"ETwo{tag}Spearman", f"{st['spearman_area_vs_ugb']:.2f}"); m(f"ETwo{tag}WireSpearman", f"{st['spearman_wire_vs_ugb']:.2f}")
    m(f"ETwo{tag}CondSpearman", f"{st['spearman_conductor_vs_ugb']:.2f}")
    m(f"ETwo{tag}UgbSpread", f"{st['ugb_relative_spread']*100:.2f}"); m(f"ETwo{tag}AreaSpread", f"{st['area_relative_spread']*100:.0f}")
    m(f"ETwo{tag}BestMHz", f"{st['oracle_best_Hz']/1e6:.2f}"); m(f"ETwo{tag}MinMHz", f"{st['oracle_min_Hz']/1e6:.2f}")
    m(f"ETwo{tag}FrontierSTwo", st["frontier_S2"]); m(f"ETwo{tag}Reversals", st["pair_reversals"]); m(f"ETwo{tag}Pairs", st["ordered_pairs"])
    m(f"ETwo{tag}SOne", st.get("S1", st["S2"]))
m("ETwoOraclePoolsComplete", len(E2P))
m("ETwoOracleCandidatesMeasured", sum(st["measured"] for st in E2P.values()))
m("ETwoOracleSTwoTotal", sum(st["S2"] for st in E2P.values()))
m("ETwoOracleUnknownTotal", sum(st["unknown"] for st in E2P.values()))
pools_all = NUM.get("E2_pools", {})
m("ETwoOnlinePoolsTerminal", sum(1 for k, v in pools_all.items() if not k.startswith("full_oracle/") and v["status"] == "TERMINAL"))
m("ETwoOnlinePoolsDeclared", 24)
POOL_TAG = {"five_t_s0": "FiveTSZero", "five_t_s2": "FiveTSTwo", "compact_miller_s0": "MillerSZero", "compact_miller_s2": "MillerSTwo",
            "fvf_s0": "FvfSZero", "fvf_s2": "FvfSTwo"}
METHOD_TAG = {"fixed_area": "Area", "adaptive_geometry": "Adapt", "fixed_rc_product": "RC", "f3_calibrated": "FThree"}
for pool_id, methods in NUM.get("E2_online", {}).items():
    for method, row in methods.items():
        tag = f"ETwoOn{POOL_TAG.get(pool_id, pool_id)}{METHOD_TAG.get(method, method)}"
        m(f"{tag}N", row["n"]); m(f"{tag}SOne", row["S1"]); m(f"{tag}STwo", row["S2"]); m(f"{tag}Unknown", row["unknown"])
# ---------------- E3
groups = ["A", "R", "B", "C", "C-dist", "C-margin", "C+F3", "P-GPT", "P-rand"]
tags = {"A": "A", "R": "R", "B": "B", "C": "C", "C-dist": "CDist", "C-margin": "CMargin", "C+F3": "CFThree", "P-GPT": "PGpt", "P-rand": "PRand"}
m("EThreeRecorded", len(E3))
table_rows = []
for g in groups:
    rows = [r for r in E3 if r["group"] == g]; sel = [r for r in rows if r["class"] == "improving patch selected"]
    t = tags[g]
    m(f"EThree{t}N", len(rows)); m(f"EThree{t}Imp", len(sel))
    m(f"EThree{t}NotApplicable", sum(1 for r in rows if r["class"] == "last patch not applicable"))
    vis = med([r["visible_verified"] for r in sel]); imp = med([r["anchor_improvement"] * 100 for r in sel])
    wall = med([r["stage_wall_s"] for r in rows]); cpu = med([r["child_cpu_s"] for r in rows])
    m(f"EThree{t}Vis", f"{vis:g}" if vis is not None else "--"); m(f"EThree{t}ImpMed", f"{imp:.0f}" if imp is not None else "--")
    m(f"EThree{t}Wall", f"{wall:.0f}" if wall else "--"); m(f"EThree{t}Cpu", f"{cpu/60:.1f}" if cpu else "--")
    table_rows.append((g, len(rows), len(sel), vis, imp, wall, cpu))
main4 = [r for r in E3 if r["class"] == "improving patch selected" and r["group"] in ("A", "R", "B", "C")]
imps = [r["anchor_improvement"] * 100 for r in main4]
comp = [r["anchor_improvement"] * 100 for r in main4 if not ("five_t" in r["task_id"] or "compact_miller" in r["task_id"])]
ota = [r["anchor_improvement"] * 100 for r in main4 if ("five_t" in r["task_id"] or "compact_miller" in r["task_id"])]
walls4 = [med([r["stage_wall_s"] for r in E3 if r["group"] == g]) for g in ("A", "R", "B", "C")]
wallsP = [med([r["stage_wall_s"] for r in E3 if r["group"] == g]) for g in ("P-GPT", "P-rand", "C+F3")]
m("EThreeSearchWallMinABRC", f"{min(w for w in walls4 if w)/60:.0f}"); m("EThreeSearchWallMaxABRC", f"{max(w for w in walls4 if w)/60:.0f}")
m("EThreeSearchWallMinPF", f"{min(w for w in wallsP if w)/60:.0f}"); m("EThreeSearchWallMaxPF", f"{max(w for w in wallsP if w)/60:.0f}")
m("EThreeImpTotal", len(imps)); m("EThreeCompImpMin", f"{min(comp):.0f}"); m("EThreeCompImpMax", f"{max(comp):.0f}")
m("EThreeOtaImpMin", f"{min(ota):.0f}"); m("EThreeOtaImpMax", f"{max(ota):.0f}")
m("EThreeGptN", sum(1 for r in E3 if r["suite"] == "gpt"))
# ---------------- E3-C (Claude editing cohort) search stage, from the latest summary written by
# scripts/opus_cohort/summarize_e3_visible_stage.py; these macros override the red placeholders.
import glob
sibg_files = sorted(glob.glob(str(ROOT / "results/derived/E3_sibling_failures_*.json")))
if sibg_files:
    SIBG = json.loads(Path(sibg_files[-1]).read_text())["totals"]
    m("EThreeSiblingFailures", SIBG["drc"]["revisions"]); m("EThreeSiblingEpisodes", SIBG["drc"]["episodes"])
    m("EThreePostEditMeasurements", SIBG["post_edit_measurements"])
sib_files = sorted(glob.glob(str(ROOT / "results/derived/E3C_sibling_failures_*.json")))
if sib_files:
    SIB = json.loads(Path(sib_files[-1]).read_text())["totals"]
    m("ECThreeSiblingFailures", SIB["drc"]["revisions"]); m("ECThreeSiblingEpisodes", SIB["drc"]["episodes"])
    m("ECThreePostEditMeasurements", SIB["post_edit_measurements"])
e3c_files = sorted(glob.glob(str(ROOT / "results/derived/E3C_visible_stage_summary_*.json")))
if e3c_files:
    E3C = json.loads(Path(e3c_files[-1]).read_text())
    rows_c = [r for part in E3C["suites"].values() for r in part]
    ctags = {"A": "A", "R": "R", "B": "B", "C": "C", "C-dist": "CDist", "C-margin": "CMargin", "P-GPT": "PGpt", "P-rand": "PRand"}
    m("ECThreeRecorded", len(rows_c))
    for g, t in ctags.items():
        rows = [r for r in rows_c if r["group"] == g]; sel = [r for r in rows if r["class"] == "improving patch selected"]
        m(f"ECThree{t}N", len(rows)); m(f"ECThree{t}Imp", len(sel))
        vis = med([r["visible_verified"] for r in sel]); imp = med([r["anchor_improvement"] * 100 for r in sel])
        m(f"ECThree{t}Vis", f"{vis:g}" if vis is not None else "--"); m(f"ECThree{t}ImpMed", f"{imp:.0f}" if imp is not None else "--")
    m("ECThreeNotApplicable", sum(1 for r in rows_c if r["class"] == "last patch not applicable" and r["group"] in ("A", "R", "B", "C")))
    m("ECThreeImpTotal", sum(1 for r in rows_c if r["class"] == "improving patch selected" and r["group"] in ("A", "R", "B", "C")))
    m("ECThreeModelFailed", sum(1 for r in rows_c if r["class"] == "model failure / over budget" and r["group"] in ("A", "R", "B", "C")))
    m("ECThreeSnapshot", Path(e3c_files[-1]).name)
# ---------------- E1-C2 (Claude action-level cohort) from the figure script's classified rows
E1C = NUM.get("E1_rows_claude") or []
if E1C:
    m("ECOneRecorded", len(E1C))
    for meth in ("G0", "G1", "G2"):
        rows = [r for r in E1C if r["method"] == meth]; tag = SPELLED[meth]
        m(f"ECOne{tag}N", len(rows)); m(f"ECOne{tag}Corrupt", sum(1 for r in rows if r["class"] == "patch rejected by git apply"))
        m(f"ECOne{tag}Over", sum(1 for r in rows if r["class"] == "action over 1,024-token budget"))
        for stratum, key in (("reuse", "Reuse"), ("composition", "Comp")):
            sub = [r for r in rows if r["stratum"] == stratum]
            m(f"ECOne{tag}{key}N", len(sub)); m(f"ECOne{tag}{key}S", sum(1 for r in sub if r["class"] == "anchor S2 verified"))
    succ = [r for r in E1C if r["class"] == "anchor S2 verified"]
    m("ECOneSuccessTotal", len(succ)); m("ECOneHiddenFull", sum(1 for r in succ if r["hidden_S2"] == 16 and r["hidden_known"] == 16))
    m("ECOneHiddenUnknown", sum(1 for r in succ if r["hidden_known"] < 16)); m("ECOneHiddenFailed", sum(1 for r in succ if r["hidden_known"] == 16 and r["hidden_S2"] < 16))
    m("ECOneCorruptTotal", sum(1 for r in E1C if r["class"] == "patch rejected by git apply")); m("ECOneOverTotal", sum(1 for r in E1C if r["class"] == "action over 1,024-token budget"))
    e1_extras(E1C, "ECOne")
# ---------------- E3-C extras: gain ranges by circuit class and visible-verified ranges
if e3c_files:
    def otas(r): return "five_t" in r["task_id"] or "compact_miller" in r["task_id"]
    imp_c = [r for r in rows_c if r["class"] == "improving patch selected" and r["group"] in ("A", "R", "B", "C")]
    comp = [r["anchor_improvement"] * 100 for r in imp_c if not otas(r)]; ota = [r["anchor_improvement"] * 100 for r in imp_c if otas(r)]
    if comp: m("ECThreeCompImpMin", f"{min(comp):.0f}"); m("ECThreeCompImpMax", f"{max(comp):.0f}")
    if ota: m("ECThreeOtaImpMin", f"{min(ota):.0f}"); m("ECThreeOtaImpMax", f"{max(ota):.0f}")
    rbc = [r for r in imp_c if r["group"] in ("R", "B", "C")]
    if rbc:
        m("ECThreeRBCVisMin", min(r["visible_verified"] for r in rbc)); m("ECThreeRBCVisMax", max(r["visible_verified"] for r in rbc))
        m("ECThreeRBCSevenShare", f"{100 * sum(1 for r in rbc if r['visible_verified'] >= 7) / len(rbc):.0f}")
# ---------------- Policy cost per cohort from the session envelopes of the recorded episodes/searches
def session_usage(path):
    out = []
    try:
        for u in json.loads(Path(path).read_text()).get("usage") or []:
            uu = u.get("usage") if isinstance(u.get("usage"), dict) else u
            if isinstance(uu, dict) and uu.get("output_tokens") is not None:
                tin = (uu.get("input_tokens") or 0) + (uu.get("cache_creation_input_tokens") or 0) + (uu.get("cache_read_input_tokens") or 0)
                out.append({"input_tokens": tin, "output_tokens": uu["output_tokens"], "usd": u.get("total_cost_usd") or 0.0})
    except (ValueError, OSError):
        pass
    return out


def cost_macros(prefix, usages, physical_cpu_s):
    n = len(usages); tin = sum(u.get("input_tokens") or 0 for u in usages); tout = sum(u.get("output_tokens") or 0 for u in usages); usd = sum(u.get("usd") or 0 for u in usages)
    m(f"{prefix}Invocations", f"{n:,}"); m(f"{prefix}InputM", f"{tin/1e6:.1f}"); m(f"{prefix}OutputK", f"{tout/1e3:.0f}")
    if usd:
        m(f"{prefix}USD", f"{usd:,.0f}")
    m(f"{prefix}PhysicalCpuH", f"{physical_cpu_s/3600:.0f}")


e3g_files = sorted(glob.glob(str(ROOT / "results/derived/E3_visible_stage_summary_*.json")))
e3_gpt_rows = [r for part in json.loads(Path(e3g_files[-1]).read_text())["suites"].values() for r in part] if e3g_files else []
gpt_e1_usage = [u for r in E1 for u in (r.get("usage") or [])]
gpt_e3_usage = [u for r in e3_gpt_rows for u in session_usage(Path(r["search_json"]).parent / "session.json")]
cost_macros("EFiveGptAction", gpt_e1_usage, sum(r.get("physical_cpu_s") or 0 for r in E1))
cost_macros("EFiveGptEdit", gpt_e3_usage, sum(r.get("child_cpu_s") or 0 for r in e3_gpt_rows))
cost_macros("EFiveGpt", gpt_e1_usage + gpt_e3_usage, sum(r.get("physical_cpu_s") or 0 for r in E1) + sum(r.get("child_cpu_s") or 0 for r in e3_gpt_rows))
if E1C and e3c_files:
    cl_e1_usage = [u for r in E1C for u in (r.get("usage") or [])]
    cl_e3_usage = [u for r in rows_c for u in session_usage(Path(r["search_json"]).parent / "session.json")]
    cost_macros("EFiveClaudeAction", cl_e1_usage, sum(r.get("physical_cpu_s") or 0 for r in E1C))
    cost_macros("EFiveClaudeEdit", cl_e3_usage, sum(r.get("child_cpu_s") or 0 for r in rows_c))
    cost_macros("EFiveClaude", cl_e1_usage + cl_e3_usage, sum(r.get("physical_cpu_s") or 0 for r in E1C) + sum(r.get("child_cpu_s") or 0 for r in rows_c))
tex = ["% Generated by scripts/write_paper_numbers.py from run records; do not edit by hand."]
for k, v in macros.items():
    tex.append(f"\\newcommand{{\\{k}}}{{{v}}}")
(ROOT / "paper/numbers.tex").write_text("\n".join(tex) + "\n")
print("\n".join(f"{k} = {v}" for k, v in macros.items()))
print("\nTABLE II rows: group, n, improving, median visible verified, median improvement %, median wall s, median cpu s")
for row in table_rows:
    print(row)
