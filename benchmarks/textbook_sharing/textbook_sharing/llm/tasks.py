"""Build the model-visible task packages.  Evaluator-side; writes only allowed content into
<runs>/model_tasks/<task_id>/ (task.md, interface.md, examples.md).  Nothing from the selection catalogue, no measured
area of any other plan, no reference program of the test topology, and no hidden case data is written there.
Main LLM tasks: topologies C02 C08 C09 C11 C16 C18 x 3 PDKs x sizes (2,1),(2,2) -> 36 requested; a task is eligible
only when its case is qualified and its reference implementation (independent mode in the main grid) passes every
automatic stage.  Examples: two development topologies (C01 basic mirror, C07 differential pair) at the nominal size in
SKY130, each with two programs and the tool reports they received (from the main-grid runs of those dev cases).
usage: python -m textbook_sharing.llm.tasks"""
from __future__ import annotations
import json
from pathlib import Path
from textbook_sharing.grid import LLM_SIZES, SELECTION_TOPOLOGIES, size_tag
from textbook_sharing import paths

OUT = paths.MODEL_TASKS
TOPO_NAMES = {"C01": "basic current mirror", "C02": "cascode current mirror", "C07": "differential pair with current-source loads",
              "C08": "five-transistor OTA", "C09": "telescopic OTA (single-ended)", "C11": "two-stage Miller op amp with RC compensation",
              "C16": "differential pair with resistor loads", "C18": "class-AB source-follower output stage"}
PDK_NAMES = {"sky130": "SkyWater SKY130 (1.8 V devices)", "gf180": "GlobalFoundries GF180MCU (3.3 V devices)", "ihp130": "IHP SG13G2 (1.2 V low-voltage devices)"}


def groups_text(case_dir):
    from textbook_sharing.run_case import load_case_dir
    from textbook_sharing.circuits import CIRCUITS
    from textbook_sharing.layout import device_specs, sharing_groups
    case, cj = load_case_dir(case_dir); circ = CIRCUITS[case.circuit_id]
    groups = sharing_groups(device_specs(circ, case.sizing))
    lines = []
    for gi, g in enumerate(groups):
        row = "bottom (NMOS) row" if g[0].model_role == "nfet" else "middle (PMOS) row"
        lines.append(f"group {gi} ({row}, body {g[0].b}, unit finger width {g[0].unit_width:g} um, L {g[0].length:g} um):")
        for d in g:
            lines.append(f"    {d.logical_id}: {d.model_role} D={d.d} G={d.g} S={d.s} B={d.b}, nf={d.nf}, total W={d.width_total:g} um")
    passives = [d for d in circ.devices if d.kind in ("res", "cap")]
    if passives:
        lines.append("passive row (fixed, not part of any plan): " + ", ".join(f"{d.name} ({d.kind} {d.nets[0]}-{d.nets[1]})" for d in passives))
    return "\n".join(lines), len(groups)


def task_text(case_dir):
    cj = json.load(open(Path(case_dir) / "case.json"))
    gt, ng = groups_text(case_dir)
    netlist = (Path(case_dir) / "target.spice").read_text()
    return f"""# Task {cj['case_id']}
Circuit: {TOPO_NAMES.get(cj['circuit_id'], cj['circuit_id'])} (textbook topology {cj['circuit_id']}).
Process: {PDK_NAMES[cj['pdk']]}.
Target netlist (fixed; sizes in um):
```spice
{netlist.strip()}
```
Fixed sharing groups and rows ({ng} groups; you must give a plan for every group index):
{gt}
Goal: propose plans so that the generated layout passes every check with the smallest full bounding-box area.
"""


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    tasks = []; excluded = []
    for cid in SELECTION_TOPOLOGIES:
        for pdk in ("sky130", "gf180", "ihp130"):
            for sw, sl in LLM_SIZES:
                tag = size_tag(sw, sl); tid = f"{cid}_{pdk}_{tag}"
                cdir = paths.CASES / cid / pdk / tag
                q = cdir / "qualification.json"
                if not q.exists(): excluded.append({"task_id": tid, "reason": "no case (parameter-illegal or duplicate request)"}); continue
                if json.load(open(q))["stage"] != "qualified":
                    excluded.append({"task_id": tid, "reason": "schematic not qualified: " + "; ".join(json.load(open(q))["qualification"]["reasons"][:2])}); continue
                ref = paths.GRID_RUNS / cid / pdk / tag / "independent" / "result.json"
                if not ref.exists() or json.load(open(ref)).get("primary_status") != "auto_passed":
                    excluded.append({"task_id": tid, "reason": "no passing reference implementation" if ref.exists() else "reference not run"}); continue
                td = OUT / tid; td.mkdir(parents=True, exist_ok=True)
                (td / "task.md").write_text(task_text(cdir))
                (td / "interface.md").write_text(Path(__file__).with_name("interface_sharing.md").read_text())
                tasks.append({"task_id": tid, "case_dir": paths.rel(cdir)})
    json.dump({"tasks": tasks, "excluded": excluded}, open(OUT / "tasks.json", "w"), indent=1)
    print("eligible", len(tasks), "excluded", len(excluded))
    for e in excluded: print("  ", e)


if __name__ == "__main__":
    main()
