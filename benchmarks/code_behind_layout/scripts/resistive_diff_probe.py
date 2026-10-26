"""Independent electrical and physical qualification of a differential stage."""
import json
from pathlib import Path
import subprocess
import sys
import numpy as np

sys.path.insert(0, "/work")
from src.generators.resistive_diff_reference import schematic, DEFAULT, PORTS
from src.spice_validation import validate_analysis
from src.corpus_metrics import frequency_3db

out = Path.cwd()
gold = out / "gold.spice"
gold.write_text(schematic())
record = {"scope": "development_independent_resistive_diff_not_formal_or_train", "sizing": DEFAULT,
    "bench": {"supply_V": 1.8, "temperature_C": 27, "reference_A": 20e-6, "input_common_mode_V": 1.2,
        "external_load_each_ohm": 100000, "external_load_each_F": 1e-12,
        "differential_input_step_V": [-.001, .001]},
    "interpretation": "Open-loop differential gain v(OUTN)-v(OUTP) per v(VINP)-v(VINN); external resistor loads and current supply are stated explicitly. TAIL is an intentional diagnostic port in both gold and layout.",
    "prelayout": {}, "post_rc": {}}


def save():
    (out / "validation.json").write_text(json.dumps(record, indent=2, allow_nan=False) + "\n")


def measure(netlist, cell, fidelity, corner, ports=PORTS):
    work = out / fidelity / corner
    work.mkdir(parents=True)
    (work / ".spiceinit").write_text("set ngbehavior=hsa\n")
    binding = {"VINP": "vp", "VINN": "vn", "OUTP": "op", "OUTN": "on", "IBIAS": "bias", "TAIL": "tail", "VSS": "0"}
    common = ["Independent differential stage qualification",
        ".lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice " + corner,
        ".option scale=1e-6 klu reltol=1e-6 abstol=1e-14 vntol=1e-8 chgtol=1e-16",
        ".temp 27", ".include " + str(netlist), "VSUPPLY vdd 0 1.8", "VBIASSUPPLY vb 0 1.8",
        "IREF vb bias 20u", "VCM cm 0 1.2", "EP vp cm x 0 .5", "EN vn cm x 0 -.5",
        "RP vdd op 100k", "RN vdd on 100k", "CP op 0 1p", "CN on 0 1p",
        "XDUT " + " ".join(binding[name.upper()] for name in ports) + " " + cell]
    vectors = "v(vp) v(vn) v(op) v(on) v(bias) v(tail) i(vsupply) i(vbiassupply)"
    bodies = {
        "ac": ["VDIFF x 0 dc 0 ac 1", ".control", "op", "wrdata op.dat " + vectors,
               "ac dec 30 10 1G", "let response=v(on)-v(op)", "wrdata ac.dat real(response) imag(response)"],
        "dc": ["VDIFF x 0 0", ".control", "dc VDIFF -.01 .01 .001", "wrdata dc.dat " + vectors],
        "tran": ["VDIFF x 0 pulse(-.001 .001 1u 10n 10n 1u 2u)", ".control", "tran 5n 4u",
                 "wrdata tran.dat v(vp) v(vn) v(op) v(on) v(bias) v(tail)"]}
    contracts = {"ac": {"kind": "ac", "columns": 3, "start": 10, "end": 1e9, "points": 241, "scale": "log"},
        "dc": {"kind": "dc", "columns": 9, "start": -.01, "end": .01, "points": 21, "scale": "linear"},
        "tran": {"kind": "transient", "columns": 7, "start": 0, "end": 4e-6,
                 "required_windows": [[1.8e-6, 1.99e-6], [2.8e-6, 2.99e-6]]}}
    result = {"analyses": {}}
    for name, body in bodies.items():
        index = body.index(".control")
        deck = common + body[:index + 1] + ["set wr_vecnames", "set wr_singlescale"] + body[index + 1:] + ["quit", ".endc", ".end", ""]
        (work / (name + ".spice")).write_text("\n".join(deck))
        try:
            with (work / (name + "_console.log")).open("w") as log:
                p = subprocess.run(["ngspice", "-b", "-o", name + ".log", name + ".spice"],
                    cwd=work, stdout=log, stderr=subprocess.STDOUT, timeout=120)
            code = p.returncode
        except subprocess.TimeoutExpired:
            code = None
        result["analyses"][name] = {"returncode": code,
            **validate_analysis(work / (name + ".dat"), work / (name + ".log"), contracts[name], code)}
        if name == "ac":
            result["analyses"]["op"] = {"returncode": code, **validate_analysis(work / "op.dat", work / "ac.log",
                {"kind": "op", "columns": 9, "expected_rows": 1}, code)}
    result["complete"] = all(row["complete"] for row in result["analyses"].values())
    if result["complete"]:
        op = np.loadtxt(work / "op.dat", skiprows=1, ndmin=2)[0]
        ac = np.loadtxt(work / "ac.dat", skiprows=1, ndmin=2)
        dc = np.loadtxt(work / "dc.dat", skiprows=1, ndmin=2)
        tran = np.loadtxt(work / "tran.dat", skiprows=1, ndmin=2)
        windows = [(tran[:, 0] >= start) & (tran[:, 0] <= end) for start, end in [(1.8e-6, 1.99e-6), (2.8e-6, 2.99e-6)]]
        differential = tran[:, 4] - tran[:, 3]
        result["metrics"] = {"output_common_mode_V": float((op[3] + op[4]) / 2),
            "tail_voltage_V": float(op[6]), "bias_voltage_V": float(op[5]),
            "output_imbalance_V": float(op[4] - op[3]), "gain_10Hz": float(ac[0, 1]),
            "bandwidth_3db_Hz": frequency_3db(work / "ac.dat"),
            "supply_power_including_reference_W": float(-1.8 * (op[7] + op[8])),
            "settled_differential_gain": float((np.mean(differential[windows[0]]) - np.mean(differential[windows[1]])) / .002),
            "transient_node_range_V": [float(np.min(tran[:, 1:])), float(np.max(tran[:, 1:]))],
            "sampled_dc_transfer": [{"differential_input_V": float(row[0]), "differential_output_V": float(row[4] - row[3])} for row in dc]}
        result["electrical_meaning"] = bool(ac[0, 1] > 1 and 0 < op[3] < 1.8 and 0 < op[4] < 1.8
            and np.all((tran[:, 1:] >= 0) & (tran[:, 1:] <= 1.8)))
    return result


for corner in ["tt", "ss", "ff"]:
    record["prelayout"][corner] = measure(gold, "resistive_diff", "prelayout", corner)
    save()
if not all(row["complete"] and row.get("electrical_meaning") for row in record["prelayout"].values()):
    raise SystemExit(2)

from glayout import sky130
from src.generators.resistive_diff import build
from src.physical_drc import check_gds
from src.report_parsers import netgen_lvs_report, rc_netlist_inventory
gds = build(out)
record["DRC"] = check_gds(gds, out / "drc_full")
save()
sky130.lvs_netgen(gds, "resistive_diff", pdk_root="/foss/pdks",
    magic_drc_file="/foss/pdks/sky130A/libs.tech/magic/sky130A.magicrc",
    lvs_setup_tcl_file="/foss/pdks/sky130A/libs.tech/netgen/sky130A_setup.tcl",
    lvs_schematic_ref_file="/work/vendor/glayout/src/glayout/pdk/sky130_mapped/sky130_fd_sc_hd.spice",
    netlist=gold, output_file_path=out / "lvs", copy_intermediate_files=True)
record["LVS"] = netgen_lvs_report(next((out / "lvs").rglob("*_lvs.rpt")).read_text())
save()
if not record["DRC"]["is_clean"] or not record["LVS"]["is_clean"]:
    raise SystemExit(2)
with (out / "pex.log").open("w") as log:
    pex = subprocess.run(["bash", "/work/vendor/glayout/src/glayout/verification/run_pex.sh", str(gds), "resistive_diff"],
        stdout=log, stderr=subprocess.STDOUT, timeout=240)
netlist = out / "resistive_diff_pex.spice"
record["pex_returncode"] = pex.returncode
record["RC"] = rc_netlist_inventory(netlist.read_text(), "resistive_diff_rc", PORTS)
save()
if pex.returncode or not record["RC"]["has_real_RC"]:
    raise SystemExit(2)
for corner in ["tt", "ss", "ff"]:
    record["post_rc"][corner] = measure(netlist, "resistive_diff_rc", "post_rc", corner, record["RC"]["ports"])
    save()
record["flow_complete"] = all(row["complete"] and row.get("electrical_meaning") for row in record["post_rc"].values())
save()
print(json.dumps(record, indent=2), flush=True)
raise SystemExit(0 if record["flow_complete"] else 2)
