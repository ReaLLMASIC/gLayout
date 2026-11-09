"""Schematic-level pre-simulation of a case (PDK models, ideal passives) to validate sizing/bias/specs
before any layout exists.  Also used post-layout with the PEX netlist by passing include_override."""
from __future__ import annotations
import json
from pathlib import Path
from .netlist import emit_subckt
from .testbench import make_testbench, check_specs, derived
from .verify.pex_sim import simulate, read_measures


def presim(pdk, circuit, case, out_dir, include_override=None, dut_name=None, corner="tt", passives="pdk"):
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    name = dut_name or f"{circuit.circuit_id}_{pdk}_{case.size}"
    if include_override is None:
        inc = out_dir / f"{name}_schematic.spice"
        inc.write_text(emit_subckt(pdk, circuit, case.sizing, name, per_finger=True, passives=passives))
    else:
        inc = Path(include_override)
    tb = make_testbench(circuit, name, str(inc), case, pdk)
    s = simulate(pdk, tb, out_dir, name=f"tb_{name}", corner=corner)
    meas = derived(read_measures(Path(s["out"]).read_text(errors="replace"))) if Path(s["out"]).exists() else {}
    sp = check_specs(meas, case.specs) if case.specs else {"ok": None, "status": "no_specs", "details": {}}
    res = {"sim": {k: v for k, v in s.items() if k != "errors"} | {"errors": s["errors"]}, "measures": meas, "spec": sp, "include": str(inc), "dut": name,
           "status": s["status"] if s["status"] != "passed" else sp["status"]}
    json.dump(res, open(out_dir / f"presim_{name}.json", "w"), indent=1, default=str)
    return res
