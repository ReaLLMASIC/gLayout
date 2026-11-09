"""Layout of a whole benchmark circuit from per-group sharing plans.

Grouping rule (identical for every circuit and plan):
  * devices are split by polarity (rows) and body net;
  * within a row, devices form *sharing groups*: the connected components of the graph whose edges join two devices
    that (a) have the same length and unit finger width and (b) share a source/drain net or a gate net;
  * each group is drawn by glayout.sharing.build_mos_group from its plan;
  * rows: NMOS (bottom), PMOS (top, mirrored), passives (top row, if any); assembly.assemble adds body ties, routing
    channels with metal-3 trunks, risers and port labels.
A plan changes only what is inside a group cell; placement order, routing policy, taps and labels are the same for every
plan, so area differences between two layouts of one circuit come from their plans.
"""
from __future__ import annotations
from glayout.sharing import DeviceSpec, build_mos_group
from textbook_sharing.assembly import RowSpec, assemble
from textbook_sharing.assembly.adapters import from_group_result
from textbook_sharing.assembly.passives import resistor_pincell, mimcap_pincell
from textbook_sharing.netlist import Circuit

MODES = ("independent", "diffusion_only", "gate_only", "combined")


def device_specs(circuit: Circuit, sizing: dict) -> list[DeviceSpec]:
    out = []
    for d in circuit.devices:
        if d.kind in ("nfet", "pfet"):
            sz = sizing[d.name]
            out.append(DeviceSpec(d.name, d.kind, d.nets[0], d.nets[1], d.nets[2], d.nets[3], float(sz["w"]), float(sz["l"]), int(sz.get("nf", 1))))
    return out


def sharing_groups(devs: list[DeviceSpec]) -> list[list[DeviceSpec]]:
    """Connected components over (same polarity, body, L, unit width) devices that share an S/D or gate net."""
    n = len(devs); parent = list(range(n))
    def find(i):
        while parent[i] != i: parent[i] = parent[parent[i]]; i = parent[i]
        return i
    def union(i, j): parent[find(i)] = find(j)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = devs[i], devs[j]
            if a.model_role != b.model_role or a.b != b.b: continue
            if abs(a.length - b.length) > 1e-6 or abs(a.unit_width - b.unit_width) > 1e-6: continue
            if ({a.s, a.d} & {b.s, b.d}) or a.g == b.g:
                union(i, j)
    comps = {}
    for i in range(n): comps.setdefault(find(i), []).append(devs[i])
    # keep netlist order inside and across groups
    return sorted(comps.values(), key=lambda g: min(devs.index(d) for d in g))


def applicability(pdk, circuit: Circuit, sizing: dict) -> dict:
    """A named mode applies to a circuit when at least one sharing group has a named plan for it (named_plans: a legal
    plan in the fixed axis order that really shares that kind)."""
    from glayout.sharing import group_candidates, named_plans
    devs = device_specs(circuit, sizing); groups = sharing_groups(devs)
    per = []
    for g in groups:
        cand = group_candidates(pdk, g); nm = named_plans(pdk, g, cand)
        per.append({"devices": [d.logical_id for d in g], "counts": cand["counts"], "named": {k: (v.plan_id() if v else None) for k, v in nm.items()}})
    modes = {m: any(pg["named"].get(m) for pg in per) for m in MODES}; modes["independent"] = True
    return {"modes": modes, "groups": per}



def build(pdk, circuit: Circuit, sizing: dict, mode: str = "independent", name: str | None = None, plans: dict | None = None):
    """Build a whole circuit.  plans: {group_index(str): SharingPlan json} (an explicit candidate); otherwise every group
    uses its named plan for `mode`, or its independent plan when the mode does not apply to that group.  Every plan gets
    the same rows, assembly rule (assembly.assemble with the two-strategy channel rule), taps and labels."""
    from glayout.sharing import SharingPlan, group_candidates, named_plans
    devs = device_specs(circuit, sizing); groups = sharing_groups(devs)
    rows = {"n": [], "p": [], "passive": []}
    for d in circuit.devices:
        if d.kind == "res":
            sz = sizing[d.name]
            rows["passive"].append(resistor_pincell(pdk, d.name, d.nets[0], d.nets[1], float(sz["r"]), body_net=sz.get("body", "VSS")))
        elif d.kind == "cap":
            sz = sizing[d.name]
            rows["passive"].append(mimcap_pincell(pdk, d.name, d.nets[0], d.nets[1], float(sz["c"])))
    applied = []; evidence = []; nf_total = 0
    for gi, g in enumerate(groups):
        pol = "n" if g[0].model_role == "nfet" else "p"
        if plans and str(gi) in plans:
            plan = SharingPlan.from_json(plans[str(gi)]); src = "explicit"
        else:
            nm = named_plans(pdk, g)
            plan = nm.get(mode) or nm["independent"]; src = "named" if nm.get(mode) else "named_fallback_independent"
        res = build_mos_group(pdk, g, plan=plan, name=f"grp{gi}")
        rows[pol].append(from_group_result(res, f"grp{gi}", pol, g[0].b))
        applied.append({"group": gi, "devices": [d.logical_id for d in g], "plan": res.applied_plan, "mode_requested": mode, "plan_source": src,
                        "plan_mode_label": plan.mode_label})
        evidence.append(res.physical_sharing_evidence); nf_total += sum(d.nf for d in g)
    row_specs = []
    if rows["n"]: row_specs.append(RowSpec(rows["n"], "n", False, rows["n"][0].body_net))
    if rows["p"]: row_specs.append(RowSpec(rows["p"], "p", True, rows["p"][0].body_net))
    if rows["passive"]: row_specs.append(RowSpec(rows["passive"], "passive", True, None, taps=False))
    top = name or f"{circuit.circuit_id}_{pdk.name}_{mode}"
    asm = assemble(pdk, row_specs, circuit.ports, name=top)
    return {"component": asm["component"], "name": top, "groups": [[d.logical_id for d in g] for g in groups], "applied_plans": applied, "evidence": evidence,
            "assembly_stats": asm["stats"], "expected_fingers": nf_total, "trunks": asm["trunks"]}
