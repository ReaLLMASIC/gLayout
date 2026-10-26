"""Development load feasibility of the independent intended FVF circuit."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import numpy as np

sys.path.insert(0, "/work/scripts")
from fvf_reference import intended_reference

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--corner", required=True, choices=["tt", "ss", "ff"])
a = p.parse_args()
out = Path.cwd()
(out / "fvf7.spice").write_text(intended_reference())
record = {"scope": "development_load_feasibility_not_physical_measurement_or_training", "corner": a.corner,
          "solver_tolerances": {"reltol": 1e-6, "abstol": 1e-14, "vntol": 1e-8, "chgtol": 1e-16}, "loads": {}}
for load in [1, 3, 10, 30]:
    work = out / (str(load) + "p"); work.mkdir()
    (work / ".spiceinit").write_text("set ngbehavior=hsa\n")
    deck = ["FVF independent-reference load feasibility", ".lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice " + a.corner,
        ".option scale=1e-6 klu reltol=1e-6 abstol=1e-14 vntol=1e-8 chgtol=1e-16", ".temp 27",
        ".include " + str(out / "fvf7.spice"), "VSUPPLY vdd 0 1.8", "IBIAS1 vdd bias1 10u", "IBIAS2 vdd bias2 10u",
        f"CLOAD out 0 {load}p", "XDUT vdd vp vn out bias1 bias2 0 fvf7", "VIN vp 0 dc .9 ac 1",
        "LSERVO out vn 1G", "CAC vn 0 1G", ".save v(out) v(vp) v(vn) v(bias1) v(bias2) i(vsupply)",
        ".control", "op", "set wr_vecnames", "set wr_singlescale",
        "wrdata operating_point.dat v(out) v(bias1) v(bias2) i(vsupply)",
        "ac dec 30 10 1G", "wrdata ac.dat real(v(out)) imag(v(out))", "quit", ".endc", ".end", ""]
    (work / "ac.spice").write_text("\n".join(deck))
    with (work / "console.log").open("w") as log:
        try:
            sim = subprocess.run(["ngspice", "-b", "-o", "ngspice.log", "ac.spice"], cwd=work,
                stdout=log, stderr=subprocess.STDOUT, timeout=90)
            result = {"returncode": sim.returncode}
        except subprocess.TimeoutExpired:
            result = {"returncode": None, "timeout": True}
    if (work / "ac.dat").exists():
        ac = np.loadtxt(work / "ac.dat", skiprows=1, ndmin=2)
        if ac.shape[1] == 3 and np.all(np.isfinite(ac)):
            response = ac[:, 1] + 1j*ac[:, 2]
            gain = 20*np.log10(np.maximum(np.abs(response), 1e-300))
            phase = np.unwrap(np.angle(response))*180/np.pi
            cross = np.flatnonzero((gain[:-1] >= 0) & (gain[1:] < 0))
            result.update(gain_at_10Hz_dB=float(gain[0]), gain_at_10Hz_real=float(response[0].real))
            if len(cross):
                i = int(cross[0]); t = -gain[i]/(gain[i+1]-gain[i])
                result.update(ugb_Hz=float(np.exp(np.log(ac[i, 0])+t*np.log(ac[i+1, 0]/ac[i, 0]))),
                    phase_margin_deg=float(180+phase[i]+t*(phase[i+1]-phase[i])))
    if (work / "operating_point.dat").exists():
        op = np.loadtxt(work / "operating_point.dat", skiprows=1, ndmin=2)
        if op.shape[1] == 5 and np.all(np.isfinite(op)):
            r = op[-1]
            result.update(output_bias_V=float(r[1]), bias1_V=float(r[2]), bias2_V=float(r[3]), power_W=float(-1.8*r[4]))
    record["loads"][str(load)+"p"] = result
    (out / "load_calibration.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({"load_pF": load, **result}), flush=True)
