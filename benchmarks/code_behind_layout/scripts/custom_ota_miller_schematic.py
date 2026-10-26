"""Tight-numerics three-corner development bench for a new Miller OTA schematic."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import numpy as np

sys.path.insert(0, "/work")
from src.generators.compact_miller_reference import DEFAULT, PORTS, schematic
from src.spice_validation import validate_analysis
from src.report_parsers import rc_netlist_inventory

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--load-pf", type=float, nargs="+", default=[1, 2])
p.add_argument("--vcm", type=float, default=1.05)
p.add_argument("--cap-size", type=float, default=25)
p.add_argument("--n-bias-ua", type=float, default=20)
p.add_argument("--p-bias-ua", type=float, default=10)
p.add_argument("--post-rc", action="store_true")
a = p.parse_args()
out = Path.cwd()
sizes = {**DEFAULT, "cap_size": a.cap_size}
source = out / "compact_miller_ota.spice"
nodes = "vdd 0 bn bp vp vn out"
subcircuit = "compact_miller_ota"
tail_node, mirror_node, stage1_node = "tail", "mirror", "stage1"
physical_input = None
if a.post_rc:
    physical_input=Path(os.environ["PROBE_INPUT"])
    physical=json.loads((physical_input/"validation.json").read_text())
    if not physical.get("physical_connectivity_and_positive_RC"):
        raise ValueError("Actual full DRC/LVS and positive RC are required before postlayout simulation")
    sizes=json.loads((physical_input/"sizing.json").read_text())
    text=(physical_input/"compact_miller_ota_pex.spice").read_text()
    inventory=rc_netlist_inventory(text,"compact_miller_ota_rc",PORTS)
    if not inventory["has_real_RC"]:
        raise ValueError("Actual extracted interface/positive RC check failed")
    source=out/"compact_miller_ota_rc.spice";source.write_text(text)
    subcircuit="compact_miller_ota_rc"
    binding={"VDD":"vdd","GND":"0","IBIASN":"bn","IBIASP":"bp","VP":"vp","VN":"vn","VOUT":"out"}
    nodes=" ".join(binding[port.upper()] for port in inventory["ports"])
    parent={}
    def root(node):
        node=node.upper();parent.setdefault(node,node);representative=node
        while parent[representative]!=representative:representative=parent[representative]
        while parent[node]!=node:
            following=parent[node];parent[node]=representative;node=following
        return representative
    def union(left,right):parent[root(left)]=root(right)
    union("GND","0")
    mos=[]
    for line in text.splitlines():
        fields=line.split()
        if not fields:continue
        if fields[0].upper().startswith("R") and len(fields)>=4:union(fields[1],fields[2])
        if fields[0].upper().startswith("X") and len(fields)>=6 and "fet_01v8" in fields[5]:mos.append(fields)
    tails=[row[1] for row in mos if "nfet" in row[5] and root(row[2])==root("IBIASN") and root(row[3])==root("GND") and root(row[1])!=root("IBIASN")]
    mirrors=[row[1] for row in mos if "pfet" in row[5] and root(row[1])==root(row[2]) and root(row[2])!=root("IBIASP")]
    stages=[row[2] for row in mos if "nfet" in row[5] and root(row[1])==root("VOUT") and root(row[3])==root("GND") and root(row[2])!=root("IBIASN")]
    if not tails or not mirrors or not stages:raise ValueError("Actual RC/MOS connectivity does not bind the intended internal probes")
    tail_node,mirror_node,stage1_node=tails[0],mirrors[0],stages[0]
(out / "compact_miller_ota.spice").write_text(schematic(sizes))
(out / "reference_definition.py").write_text(Path("/work/src/generators/compact_miller_reference.py").read_text())
(out / "sizing.json").write_text(json.dumps(sizes, indent=2) + "\n")
record = {"scope": "development_independent_Miller_"+("post_RC" if a.post_rc else "schematic")+"_not_formal_or_training", "sizing": sizes,
          "physical_input":str(physical_input) if physical_input else None,
          "internal_probe_nodes":{"tail":tail_node,"mirror":mirror_node,"stage1":stage1_node},
          "vcm_V": a.vcm, "n_reference_uA": a.n_bias_ua, "p_reference_uA": a.p_bias_ua, "results": {},
          "numerics": {"reltol": 1e-6, "abstol": 1e-14, "vntol": 1e-8, "chgtol": 1e-16}}


def measure(corner, load):
    name = corner + "_" + str(load) + "pF"
    work = out / name
    work.mkdir()
    (work / ".spiceinit").write_text("set ngbehavior=hsa\n")
    common = ["Independent Miller OTA development feasibility",
              ".lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice " + corner,
              ".option scale=1e-6 klu", ".option reltol=1e-6 abstol=1e-14 vntol=1e-8 chgtol=1e-16", ".temp 27",
              ".include " + str(source), "VSUPPLY vdd 0 1.8", f"IBN vdd bn {a.n_bias_ua:g}u",
              f"IBP bp 0 {a.p_bias_ua:g}u", f"CLOAD out 0 {load:g}p",
              "XDUT "+nodes+" "+subcircuit]
    tail_probe,mirror_probe,stage1_probe=["v(xdut."+node+")" for node in [tail_node,mirror_node,stage1_node]]
    save = ".save v(out) v(vp) v(vn) v(bn) v(bp) "+tail_probe+" "+mirror_probe+" "+stage1_probe+" i(vsupply)"
    analyses = {
        "ac": [f"VIN vp 0 dc {a.vcm:g} ac 1", "LSERVO out vn 1G", "CAC vn 0 1G", save,
               ".control", "op", "set wr_vecnames", "set wr_singlescale",
               "wrdata op.dat v(out) v(bn) v(bp) "+tail_probe+" "+mirror_probe+" "+stage1_probe+" i(vsupply)",
               "ac dec 50 10 1G", "wrdata ac.dat real(v(out)) imag(v(out))"],
        "tran": ["VFB out vn 0", f"VIN vp 0 pulse({a.vcm-.01:g} {a.vcm+.01:g} 1u 10n 10n 1u 2u)", save,
                 ".control", "set wr_vecnames", "set wr_singlescale", "tran 2n 4u", "wrdata tran.dat v(vp) v(out)"],
        "dc": ["VFB out vn 0", f"VIN vp 0 {a.vcm:g}", save, ".control", "set wr_vecnames", "set wr_singlescale",
               "dc VIN .95 1.15 .05", "wrdata dc.dat v(vp) v(out) "+tail_probe+" "+stage1_probe]}
    contracts = {"ac": {"kind": "ac", "columns": 3, "start": 10, "end": 1e9, "points": 401, "scale": "log"},
                 "tran": {"kind": "transient", "columns": 3, "start": 0, "end": 4e-6, "required_windows": [[1.8e-6, 1.99e-6]]},
                 "dc": {"kind": "dc", "columns": 5, "start": .95, "end": 1.15, "points": 5, "scale": "linear"}}
    result = {"corner": corner, "load_pF": load, "analyses": {}}
    for analysis, body in analyses.items():
        deck = work / (analysis + ".spice")
        deck.write_text("\n".join(common + body + ["quit", ".endc", ".end", ""]))
        started = time.monotonic()
        with (work / (analysis + "_console.log")).open("w") as log:
            try:
                run = subprocess.run(["ngspice", "-b", "-o", analysis + ".log", deck.name], cwd=work,
                    stdout=log, stderr=subprocess.STDOUT, timeout=120)
            except subprocess.TimeoutExpired:
                result["analyses"][analysis] = {"timeout": True, "wall_seconds": time.monotonic()-started}
                return name, result
        result["analyses"][analysis] = {"returncode": run.returncode, "wall_seconds": time.monotonic()-started,
            "integrity": validate_analysis(work / (analysis + ".dat"), work / (analysis + ".log"), contracts[analysis], returncode=run.returncode)}
        if analysis == "ac":
            result["op_integrity"] = validate_analysis(work / "op.dat", work / "ac.log", {"kind": "op", "columns": 8, "expected_rows": 1}, returncode=run.returncode)
    if not result.get("op_integrity", {}).get("complete") or not all(item["integrity"]["complete"] for item in result["analyses"].values()):
        return name, result
    op = np.loadtxt(work / "op.dat", skiprows=1, ndmin=2)
    ac = np.loadtxt(work / "ac.dat", skiprows=1, ndmin=2)
    tran = np.loadtxt(work / "tran.dat", skiprows=1, ndmin=2)
    dc = np.loadtxt(work / "dc.dat", skiprows=1, ndmin=2)
    response = ac[:, 1] + 1j*ac[:, 2]
    db, phase = 20*np.log10(np.abs(response)), np.unwrap(np.angle(response))*180/np.pi
    crossings = np.flatnonzero((db[:-1] >= 0) & (db[1:] < 0))
    result.update(output_V=float(op[-1, 1]), n_bias_V=float(op[-1, 2]), p_bias_V=float(op[-1, 3]),
        tail_V=float(op[-1, 4]), mirror_V=float(op[-1, 5]), stage1_V=float(op[-1, 6]),
        supply_current_A=float(-op[-1, 7]), power_W=float(-1.8*op[-1, 7]), gain_10Hz_dB=float(db[0]),
        positive_low_frequency_gain=bool(response[0].real > 0 and abs(phase[0]) < 10),
        maximum_dc_tracking_error_V=float(np.max(np.abs(dc[:, 1] - dc[:, 2]))))
    if len(crossings):
        i = int(crossings[0]); fraction = -db[i]/(db[i+1]-db[i])
        result.update(ugb_Hz=float(np.exp(np.log(ac[i, 0])+fraction*np.log(ac[i+1, 0]/ac[i, 0]))),
            phase_margin_deg=float(180+phase[i]+fraction*(phase[i+1]-phase[i])))
    settled = (tran[:, 0] > 1.8e-6) & (tran[:, 0] < 1.99e-6)
    result["settled_tracking_error_V"] = float(np.max(np.abs(tran[settled, 1]-tran[settled, 2])))
    result["development_nominal_feasible"] = bool(result["positive_low_frequency_gain"]
        and abs(result["output_V"]-a.vcm) < .005 and .15 < result["tail_V"] < .8 and .3 < result["stage1_V"] < 1.2
        and 50e-6 < result["supply_current_A"] < 160e-6 and result["gain_10Hz_dB"] >= 55
        and 60 <= result.get("phase_margin_deg", -1) <= 180 and result.get("ugb_Hz", 0) >= 1e6
        and result["settled_tracking_error_V"] < .005)
    return name, result


with ThreadPoolExecutor(max_workers=2) as pool:
    futures = [pool.submit(measure, corner, load) for corner in ["tt", "ss", "ff"] for load in a.load_pf]
    for future in as_completed(futures):
        name, result = future.result(); record["results"][name] = result
        (out / "measurements.json").write_text(json.dumps(record, indent=2)+"\n")
        print(json.dumps({"configuration": name, **result}), flush=True)
record["all_corners_nominal_feasible"] = all(value.get("development_nominal_feasible") for value in record["results"].values())
(out / "measurements.json").write_text(json.dumps(record, indent=2)+"\n")
raise SystemExit(0 if record["all_corners_nominal_feasible"] else 2)
