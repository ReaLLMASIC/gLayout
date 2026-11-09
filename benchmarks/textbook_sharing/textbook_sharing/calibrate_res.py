"""Fit R(l) = a*l + b for each PDK resistor model from two schematic simulations: the documented calibration of the
length formula used by assembly.passives.resistor_geometry (its CALIB table).  Writes data/res_calibration.json.
usage: python -m textbook_sharing.calibrate_res"""
import json
from pathlib import Path
from textbook_sharing import paths
from textbook_sharing.assembly.passives import RES, resistor_spice_line
from textbook_sharing.verify.pex_sim import simulate, read_measures


def main():
    out = {}
    for pdk in ("sky130", "gf180", "ihp130"):
        t = RES[pdk]; w = t["w_fixed"] or 1.0; pts = []
        for l in (5.0, 20.0):
            tb = (f".subckt rtest A B VSS\n{resistor_spice_line(pdk, '1', 'A', 'B', 'VSS', w, l)}\n.ends rtest\nX1 A B VSS rtest\n"
                  "VA A 0 1\nVB B 0 0\nVS VSS 0 0\n.control\nop\nlet r = 1/(-i(VA))\nprint r\nquit\n.endc\n.end\n")
            s = simulate(pdk, tb, paths.RUNS / "calib_res" / pdk, name=f"r_{l:g}")
            m = read_measures(open(s["out"]).read()) if Path(s["out"]).exists() else {}
            pts.append((l, m.get("r")))
        (l1, r1), (l2, r2) = pts
        a = (r2 - r1) / (l2 - l1); b = r1 - a * l1
        out[pdk] = {"w": w, "points": pts, "a_ohm_per_um": a, "b_ohm": b, "rsh_nominal_table": t["rsh"]}
        print(pdk, out[pdk])
    json.dump(out, open(paths.DATA / "res_calibration.json", "w"), indent=1)


if __name__ == "__main__":
    main()
