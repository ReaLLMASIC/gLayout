"""Build examples.md for the model sessions from REAL evaluator runs on two development topologies (C01 basic mirror,
C07 differential pair with current-source loads; SKY130, nominal size).  Neither topology is a task topology.
For each: program A in the axis shorthand, program B as an explicit SharingPlan (text rendered from a legal named plan of
that development case), and for C07 also one deliberately illegal program, so the rejection format is shown.  Every
report shown is the evaluator's own feedback text for that program.
usage: python -m textbook_sharing.llm.make_examples [--interface base]  -> <runs>/model_tasks/examples.md (+ <runs>/model_examples/<case>/ sessions)"""
from __future__ import annotations
import sys, json, subprocess
from textbook_sharing import paths
CASES = [("C01", "sky130", "sW1_sL1"), ("C07", "sky130", "sW1_sL1")]


def plan_python(pj):
    fo = ", ".join(f'("{d}", {k})' for d, k in pj["finger_order"])
    gg = ", ".join(f'GateGroup(fingers=({", ".join(str(x) for x in f)}{"," if len(f) == 1 else ""}), side="{s}", pad_end="{e}")' for f, s, e in pj["gate_groups"])
    return (f"SharingPlan(finger_order=[{fo}],\n"
            f"            orientations={json.dumps(pj['orientations'])},\n"
            f"            diffusion_joins={str(pj['diffusion_joins'])},\n"
            f"            gate_groups=[{gg}])")


def main():
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("--interface", default="sharing"); a = ap.parse_args(); base = a.interface == "base"
    from textbook_sharing.run_case import load_case_dir, pdk_obj
    from textbook_sharing.circuits import CIRCUITS
    from textbook_sharing.layout import device_specs, sharing_groups
    from glayout.sharing import named_plans
    from textbook_sharing.llm.tasks import task_text
    parts = ["Each example shows a development circuit (NOT your task circuit), programs that were submitted for it, and the tool "
             "report each program received.  Areas of development circuits say nothing about your task's areas."]
    for cid, pdk, size in CASES:
        cdir = paths.CASES / cid / pdk / size
        case, cj = load_case_dir(str(cdir)); groups = sharing_groups(device_specs(CIRCUITS[cid], case.sizing)); pk = pdk_obj(pdk)
        sd = paths.MODEL_EXAMPLES / (f"{cid}_{pdk}_{size}" + ("_base" if base else "")); sd.mkdir(parents=True, exist_ok=True)
        json.dump({"task_id": f"example_{cid}", "case_dir": paths.rel(cdir), "model_tag": "examples", "rep": 0, "interface": a.interface}, open(sd / "session.json", "w"))
        axis = ", ".join(f'{gi}: axis_plan(arrangement="block", orientation="alt_SD", diffusion="none", gate="per_device", strap_start="bottom", contact_end="left")' for gi in range(len(groups)))
        progs = [f"plans = {{{axis}}}"]
        expl = []
        for gi, g in enumerate(groups):
            nm = named_plans(pk, g); pl = nm.get("combined") or nm.get("diffusion_only") or nm["independent"]
            expl.append(f"{gi}: {plan_python(pl.to_json())}")
        progs.append("plans = {" + ",\n         ".join(expl) + "}")
        if cid == "C07":
            g0 = groups[0]; d0 = g0[0].logical_id
            bad = (f'plans = {{0: SharingPlan(finger_order=[("{d0}", 0), ("{d0}", 1)], orientations=["SD", "SD"], diffusion_joins=[True], '
                   f'gate_groups=[GateGroup(fingers=(0, 1), side="bottom", pad_end="left")])' + "".join(f", {gi}: axis_plan(arrangement=\"block\", orientation=\"alt_SD\", diffusion=\"none\", gate=\"per_device\", strap_start=\"bottom\", contact_end=\"left\")" for gi in range(1, len(groups))) + "}")
            progs.append(bad)
        if base:
            fr = lambda arr, ori, ce: f'fet_row(arrangement="{arr}", orientation="{ori}", contact_end="{ce}")'
            progs = ["plans = {" + ", ".join(f"{gi}: " + fr("block", "alt_SD", "left") for gi in range(len(groups))) + "}",
                     "plans = {" + ", ".join(f"{gi}: " + fr("interleave", "alt_DS", "right") for gi in range(len(groups))) + "}"]
            if cid == "C07":
                progs.append("plans = {" + ", ".join(f'{gi}: fet_row(arrangement="block", orientation="alt_SD", contact_end="left", diffusion="all_legal")' for gi in range(len(groups))) + "}")
        parts.append(f"\n## Example: {cid} ({pdk}, development size)\n" + task_text(str(cdir)).replace("# Task", "Case"))
        for k, prog in enumerate(progs, start=1):
            (sd / f"p{k}_answer.md").write_text(f"```python\n{prog}\n```\n")
            r = subprocess.run([sys.executable, "-m", "textbook_sharing.llm.evaluate", str(sd), str(k)], capture_output=True, text=True, cwd=str(paths.ROOT))
            fb = (sd / f"p{k}_feedback.txt").read_text() if (sd / f"p{k}_feedback.txt").exists() else ("EVALUATOR ERROR\n" + r.stderr[-800:])
            parts.append(f"\n### Program {k}\n```python\n{prog}\n```\n### Tool report for program {k}\n```\n{fb}\n```")
    out = paths.MODEL_TASKS / ("examples_base.md" if base else "examples.md"); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(parts) + "\n")
    print("written", out, len(out.read_text()), "chars")


if __name__ == "__main__":
    main()
