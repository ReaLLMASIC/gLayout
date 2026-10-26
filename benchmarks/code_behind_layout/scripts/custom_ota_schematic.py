"""Development-only independently specified OTA prelayout feasibility."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import numpy as np

sys.path.insert(0, "/work")
from src.generators.five_t_reference import DEFAULT, PORTS, schematic
from src.report_parsers import rc_netlist_inventory
from src.spice_validation import validate_analysis

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--load-pf", type=float, nargs="+", default=[2, 5])
p.add_argument("--vcm", type=float, default=1.1)
p.add_argument("--bias-ua", type=float, default=20)
p.add_argument("--post-rc", action="store_true")
a = p.parse_args()
out = Path.cwd()
source = out / "five_t_ota.spice"
source.write_text(schematic())
instance_nodes = "vdd 0 bias vp vn out"
subcircuit = "five_t_ota"
tail_node, mirror_node = "tail", "mirror"
physical_link = None
if a.post_rc:
    physical_link = Path(os.environ["PROBE_INPUT"])
    validation = json.loads((physical_link / "validation.json").read_text())
    if not validation.get("physical_connectivity_and_positive_RC"):
        raise ValueError("Post-RC simulation requires independent full DRC/LVS and positive RC")
    text = (physical_link / "five_t_ota_pex.spice").read_text()
    inventory = rc_netlist_inventory(text, "five_t_ota_rc", PORTS)
    if not inventory["has_real_RC"]:
        raise ValueError("Actual RC netlist failed strict physical-element/interface admission")
    source = out / "five_t_ota_rc.spice"
    source.write_text(text)
    binding = {"VDD": "vdd", "GND": "0", "IBIAS": "bias", "VP": "vp", "VN": "vn", "VOUT": "out"}
    instance_nodes = " ".join(binding[port.upper()] for port in inventory["ports"])
    subcircuit = "five_t_ota_rc"
    # Wire-resistance connectivity identifies the actual MOS terminal nodes for
    # internal-bias probes without adding fictitious external GDS pins.
    parent = {}
    def root(node):
        node = node.upper()
        parent.setdefault(node, node)
        representative = node
        while parent[representative] != representative:
            representative = parent[representative]
        while parent[node] != node:
            following = parent[node]
            parent[node] = representative
            node = following
        return representative
    def union(left, right):
        parent[root(left)] = root(right)
    union("GND", "0")
    mos = []
    for line in text.splitlines():
        fields = line.split()
        if not fields:
            continue
        if fields[0].upper().startswith("R") and len(fields) >= 4:
            union(fields[1], fields[2])
        if fields[0].upper().startswith("X") and len(fields) >= 6 and "fet_01v8" in fields[5]:
            mos.append(fields)
    tails = [row[1] for row in mos if "nfet" in row[5] and root(row[2]) == root("IBIAS")
             and root(row[3]) == root("GND") and root(row[1]) != root("IBIAS")]
    mirrors = [row[1] for row in mos if "pfet" in row[5] and root(row[1]) == root(row[2])]
    if not tails or not mirrors:
        raise ValueError("Extracted MOS/physical-wire connectivity cannot identify the intended internal bias nodes")
    tail_node, mirror_node = tails[0], mirrors[0]
(out / "reference_definition.py").write_text(Path("/work/src/generators/five_t_reference.py").read_text())
(out / "sizing.json").write_text(json.dumps(DEFAULT, indent=2) + "\n")
record = {"scope": "development_5T_core_" + ("post_RC" if a.post_rc else "independent_schematic") + "_not_formal_or_training",
          "topology": "five_t_ota", "sizing": DEFAULT, "vcm_V": a.vcm, "reference_current_uA": a.bias_ua,
          "physical_input": str(physical_link) if physical_link else None,
          "internal_bias_probe_nodes": {"tail": tail_node, "mirror": mirror_node},
          "results": {}, "numerics": {"reltol": 1e-6, "abstol": 1e-14, "vntol": 1e-8, "chgtol": 1e-16}}


def simulate(corner, load):
    name = corner + "_" + str(load) + "pF"
    work = out / name
    work.mkdir()
    (work / ".spiceinit").write_text("set ngbehavior=hsa\n")
    common = ["Independent 5T OTA tight-numerics development feasibility",
              ".lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice " + corner,
              ".option scale=1e-6 klu", ".option reltol=1e-6 abstol=1e-14 vntol=1e-8 chgtol=1e-16",
              ".temp 27", ".include " + str(source), "VSUPPLY vdd 0 1.8",
              f"IBIAS vdd bias {a.bias_ua:g}u", f"CLOAD out 0 {load:g}p",
              "XDUT " + instance_nodes + " " + subcircuit]
    tail_probe, mirror_probe = "v(xdut." + tail_node + ")", "v(xdut." + mirror_node + ")"
    save = ".save v(out) v(vp) v(vn) v(bias) " + tail_probe + " " + mirror_probe + " i(vsupply)"
    analyses = {
        "ac": [f"VIN vp 0 dc {a.vcm:g} ac 1", "LSERVO out vn 1G", "CAC vn 0 1G", save,
               ".control", "op", "set wr_vecnames", "set wr_singlescale",
               "wrdata op.dat v(out) v(bias) " + tail_probe + " " + mirror_probe + " i(vsupply)",
               "ac dec 50 10 1G", "wrdata ac.dat real(v(out)) imag(v(out))"],
        "tran": ["VFB out vn 0", f"VIN vp 0 pulse({a.vcm-.01:g} {a.vcm+.01:g} 1u 10n 10n 1u 2u)", save,
                 ".control", "set wr_vecnames", "set wr_singlescale", "tran 2n 4u",
                 "wrdata tran.dat v(vp) v(out)"],
        "dc": ["VFB out vn 0", f"VIN vp 0 {a.vcm:g}", save, ".control", "set wr_vecnames", "set wr_singlescale",
               "dc VIN .9 1.3 .05", "wrdata dc.dat v(vp) v(out) " + tail_probe + " " + mirror_probe]}
    result = {"corner": corner, "load_pF": load, "analyses": {}}
    for analysis, body in analyses.items():
        deck = work / (analysis + ".spice")
        deck.write_text("\n".join(common + body + ["quit", ".endc", ".end", ""]))
        started = time.monotonic()
        with (work / (analysis + "_console.log")).open("w") as log:
            try:
                process = subprocess.run(["ngspice", "-b", "-o", analysis + ".log", deck.name], cwd=work,
                    stdout=log, stderr=subprocess.STDOUT, timeout=90)
                result["analyses"][analysis] = {"returncode": process.returncode, "wall_seconds": time.monotonic()-started}
            except subprocess.TimeoutExpired:
                result["analyses"][analysis] = {"timeout": True, "wall_seconds": time.monotonic()-started}
                return name, result
        contracts = {
            "ac": {"kind": "ac", "columns": 3, "start": 10, "end": 1e9, "points": 401, "scale": "log"},
            "tran": {"kind": "transient", "columns": 3, "start": 0, "end": 4e-6, "required_windows": [[1.8e-6, 1.99e-6]]},
            "dc": {"kind": "dc", "columns": 5, "start": .9, "end": 1.3, "points": 9, "scale": "linear"}}
        data_path = work / ("ac.dat" if analysis == "ac" else analysis + ".dat")
        result["analyses"][analysis]["integrity"] = validate_analysis(data_path, work / (analysis + ".log"),
            contracts[analysis], returncode=process.returncode)
        if analysis == "ac":
            result["operating_point_integrity"] = validate_analysis(work / "op.dat", work / "ac.log",
                {"kind": "op", "columns": 6, "expected_rows": 1}, returncode=process.returncode)
    if (any(item.get("returncode") != 0 or not item.get("integrity", {}).get("complete") for item in result["analyses"].values())
            or not result.get("operating_point_integrity", {}).get("complete")):
        return name, result
    op = np.loadtxt(work / "op.dat", skiprows=1, ndmin=2)
    ac = np.loadtxt(work / "ac.dat", skiprows=1, ndmin=2)
    tran = np.loadtxt(work / "tran.dat", skiprows=1, ndmin=2)
    dc = np.loadtxt(work / "dc.dat", skiprows=1, ndmin=2)
    response = ac[:, 1] + 1j * ac[:, 2]
    gain = 20 * np.log10(np.abs(response))
    phase = np.unwrap(np.angle(response)) * 180 / np.pi
    crossings = np.flatnonzero((gain[:-1] >= 0) & (gain[1:] < 0))
    result.update(finite=all(np.all(np.isfinite(value)) for value in [op, ac, tran, dc]),
                  output_V=float(op[-1, 1]), bias_V=float(op[-1, 2]), tail_V=float(op[-1, 3]),
                  mirror_V=float(op[-1, 4]), supply_current_A=float(-op[-1, 5]),
                  power_W=float(-1.8 * op[-1, 5]), gain_10Hz_dB=float(gain[0]),
                  positive_low_frequency_gain=bool(response[0].real > 0 and abs(phase[0]) < 10),
                  maximum_dc_tracking_error_V=float(np.max(np.abs(dc[:, 1] - dc[:, 2]))))
    if len(crossings):
        index = int(crossings[0])
        fraction = -gain[index] / (gain[index+1] - gain[index])
        result.update(ugb_Hz=float(np.exp(np.log(ac[index, 0]) + fraction*np.log(ac[index+1, 0]/ac[index, 0]))),
                      phase_margin_deg=float(180 + phase[index] + fraction*(phase[index+1]-phase[index])))
    settled = (tran[:, 0] > 1.8e-6) & (tran[:, 0] < 1.99e-6)
    result["settled_tracking_error_V"] = float(np.max(np.abs(tran[settled, 1] - tran[settled, 2])))
    result["development_feasible"] = bool(result["finite"] and 0.15 < result["tail_V"] < .8
        and .4 < result["mirror_V"] < 1.6 and abs(result["output_V"] - a.vcm) < .01
        and 20e-6 < result["supply_current_A"] < 80e-6 and 60 <= result.get("phase_margin_deg", -1) <= 180
        and result["positive_low_frequency_gain"]
        and result["gain_10Hz_dB"] >= 30 and result.get("ugb_Hz", 0) >= 1e6
        and result["settled_tracking_error_V"] < .01)
    return name, result


with ThreadPoolExecutor(max_workers=2) as pool:
    futures = [pool.submit(simulate, corner, load) for corner in ["tt", "ss", "ff"] for load in a.load_pf]
    for future in as_completed(futures):
        name, result = future.result()
        record["results"][name] = result
        (out / "measurements.json").write_text(json.dumps(record, indent=2) + "\n")
        print(json.dumps({"configuration": name, **result}), flush=True)
record["development_all_corners_feasible"] = all(value.get("development_feasible") for value in record["results"].values())
(out / "measurements.json").write_text(json.dumps(record, indent=2) + "\n")
raise SystemExit(0 if record["development_all_corners_feasible"] else 2)
