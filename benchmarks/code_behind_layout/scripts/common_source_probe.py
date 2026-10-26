"""Qualify an independent common-source circuit before and after extraction."""
import json
from pathlib import Path
import subprocess
import sys
import numpy as np

sys.path.insert(0, "/work")
from src.generators.common_source_reference import schematic, DEFAULT, PORTS
from src.spice_validation import validate_analysis
from src.corpus_metrics import frequency_3db

out = Path.cwd()
gold = out / "gold.spice"
gold.write_text(schematic())
record = {"scope": "development_independent_common_source_not_formal_or_train", "sizing": DEFAULT,
    "bench": {"supply_V": 1.8, "temperature_C": 27, "p_reference_A": 20e-6,
              "external_input_replica_A": 15e-6, "load_ohm": 100000, "load_F": 1e-12,
              "input_offset_step_V": [-.0005, .0005]},
    "interpretation": "Open-loop inverting gain stage; no OTA phase-margin criterion. External diode input-bias replica has a separate supply and is outside the DUT.",
    "prelayout": {}, "post_rc": {}}


def save():
    (out / "validation.json").write_text(json.dumps(record, indent=2, allow_nan=False) + "\n")


def measure(netlist, cell, fidelity, corner, ports=PORTS):
    work = out / fidelity / corner
    work.mkdir(parents=True)
    (work / ".spiceinit").write_text("set ngbehavior=hsa\n")
    binding = {"VIN": "vin", "OUT": "out", "PBIAS": "pbias", "VDD": "vdd", "VSS": "0"}
    common = ["Independent common-source qualification",
        ".lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice " + corner,
        ".option scale=1e-6 klu reltol=1e-6 abstol=1e-14 vntol=1e-8 chgtol=1e-16",
        ".temp 27", ".include " + str(netlist), "VSUPPLY vdd 0 1.8", "IBIAS pbias 0 20u",
        "VREPLICA vr 0 1.8", "IREPLICA vr nb 15u",
        "XREPLICA nb nb 0 0 sky130_fd_pr__nfet_01v8 w=2 l=1 m=2",
        "RLOAD out 0 100k", "CLOAD out 0 1p",
        "XDUT " + " ".join(binding[name.upper()] for name in ports) + " " + cell]
    vectors = "v(vin) v(out) v(pbias) v(nb) i(vsupply)"
    bodies = {
        "ac": ["VDELTA vin nb dc 0 ac 1", ".control", "op", "wrdata op.dat " + vectors,
               "ac dec 30 10 1G", "wrdata ac.dat real(v(out)) imag(v(out))"],
        "dc": ["VDELTA vin nb 0", ".control", "dc VDELTA -.01 .01 .001", "wrdata dc.dat " + vectors],
        "tran": ["VDELTA vin nb pulse(-.0005 .0005 1u 10n 10n 1u 2u)",
                 ".control", "tran 5n 4u", "wrdata tran.dat v(vin) v(out) v(pbias) v(nb)"]}
    contracts = {"ac": {"kind": "ac", "columns": 3, "start": 10, "end": 1e9, "points": 241, "scale": "log"},
        "dc": {"kind": "dc", "columns": 6, "start": -.01, "end": .01, "points": 21, "scale": "linear"},
        "tran": {"kind": "transient", "columns": 5, "start": 0, "end": 4e-6,
                 "required_windows": [[1.8e-6, 1.99e-6], [2.8e-6, 2.99e-6]]}}
    result = {"analyses": {}}
    for name, body in bodies.items():
        index = body.index(".control")
        deck = common + body[:index + 1] + ["set wr_vecnames", "set wr_singlescale"] + body[index + 1:] + ["quit", ".endc", ".end", ""]
        (work / (name + ".spice")).write_text("\n".join(deck))
        try:
            with (work / (name + "_console.log")).open("w") as log:
                process = subprocess.run(["ngspice", "-b", "-o", name + ".log", name + ".spice"],
                    cwd=work, stdout=log, stderr=subprocess.STDOUT, timeout=120)
            code = process.returncode
        except subprocess.TimeoutExpired:
            code = None
        result["analyses"][name] = {"returncode": code,
            **validate_analysis(work / (name + ".dat"), work / (name + ".log"), contracts[name], code)}
        if name == "ac":
            result["analyses"]["op"] = {"returncode": code, **validate_analysis(work / "op.dat", work / "ac.log",
                {"kind": "op", "columns": 6, "expected_rows": 1}, code)}
    result["complete"] = all(row["complete"] for row in result["analyses"].values())
    if result["complete"]:
        op = np.loadtxt(work / "op.dat", skiprows=1, ndmin=2)[0]
        ac = np.loadtxt(work / "ac.dat", skiprows=1, ndmin=2)
        dc = np.loadtxt(work / "dc.dat", skiprows=1, ndmin=2)
        tran = np.loadtxt(work / "tran.dat", skiprows=1, ndmin=2)
        windows = [(tran[:, 0] >= start) & (tran[:, 0] <= end) for start, end in [(1.8e-6, 1.99e-6), (2.8e-6, 2.99e-6)]]
        result["metrics"] = {"input_bias_V": float(op[1]), "output_bias_V": float(op[2]),
            "pmos_bias_V": float(op[3]), "DUT_power_W": float(-1.8 * op[5]),
            "inverting_gain_10Hz": float(ac[0, 1]), "bandwidth_3db_Hz": frequency_3db(work / "ac.dat"),
            "settled_incremental_gain": float((np.mean(tran[windows[0], 2]) - np.mean(tran[windows[1], 2])) / .001),
            "output_transient_range_V": [float(min(tran[:, 2])), float(max(tran[:, 2]))],
            "sampled_dc_transfer": [{"input_offset_V": float(row[0]), "input_V": float(row[1]), "output_V": float(row[2])} for row in dc]}
        result["electrical_meaning"] = bool(ac[0, 1] < -1 and 0 < op[2] < 1.8
            and np.all((tran[:, 1:] >= 0) & (tran[:, 1:] <= 1.8)))
    return result


for corner in ["tt", "ss", "ff"]:
    record["prelayout"][corner] = measure(gold, "common_source_stage", "prelayout", corner)
    save()
if not all(row["complete"] and row.get("electrical_meaning") for row in record["prelayout"].values()):
    raise SystemExit(2)

from glayout import sky130
from src.generators.common_source_stage import build
from src.physical_drc import check_gds
from src.report_parsers import netgen_lvs_report, rc_netlist_inventory
gds = build(out)
record["DRC"] = check_gds(gds, out / "drc_full")
save()
sky130.lvs_netgen(gds, "common_source_stage", pdk_root="/foss/pdks",
    magic_drc_file="/foss/pdks/sky130A/libs.tech/magic/sky130A.magicrc",
    lvs_setup_tcl_file="/foss/pdks/sky130A/libs.tech/netgen/sky130A_setup.tcl",
    lvs_schematic_ref_file="/work/vendor/glayout/src/glayout/pdk/sky130_mapped/sky130_fd_sc_hd.spice",
    netlist=gold, output_file_path=out / "lvs", copy_intermediate_files=True)
record["LVS"] = netgen_lvs_report(next((out / "lvs").rglob("*_lvs.rpt")).read_text())
save()
if not record["DRC"]["is_clean"] or not record["LVS"]["is_clean"]:
    raise SystemExit(2)
with (out / "pex.log").open("w") as log:
    pex = subprocess.run(["bash", "/work/vendor/glayout/src/glayout/verification/run_pex.sh", str(gds), "common_source_stage"],
        stdout=log, stderr=subprocess.STDOUT, timeout=240)
netlist = out / "common_source_stage_pex.spice"
record["pex_returncode"] = pex.returncode
record["RC"] = rc_netlist_inventory(netlist.read_text(), "common_source_stage_rc", PORTS)
save()
if pex.returncode or not record["RC"]["has_real_RC"]:
    raise SystemExit(2)
for corner in ["tt", "ss", "ff"]:
    record["post_rc"][corner] = measure(netlist, "common_source_stage_rc", "post_rc", corner, record["RC"]["ports"])
    save()
record["flow_complete"] = all(row["complete"] and row.get("electrical_meaning") for row in record["post_rc"].values())
save()
print(json.dumps(record, indent=2), flush=True)
raise SystemExit(0 if record["flow_complete"] else 2)
