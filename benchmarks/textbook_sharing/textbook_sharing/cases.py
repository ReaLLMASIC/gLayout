"""Case data model: circuit x PDK x size point -> sizing, supply, bias, loads, specs.

Sizing convention: per MOS device we store the total width w (um), the length l (um) and the finger count nf; the unit
width w/nf must be at least the contactable minimum of the PDK (checked when the case is derived and again by the
builder).  The SPICE multiplier m is always 1 (parallel devices are expressed by nf).
PDK operating points: sky130 1.8 V, gf180 3.3 V, ihp130 1.2 V (low-voltage devices).
"""
from __future__ import annotations
import json, hashlib, copy
from dataclasses import dataclass, field, asdict

PDK_POINT = {
    "sky130": {"vdd": 1.8, "lmin": 0.15, "uw_min": 0.29, "ibias": 20e-6, "model_note": "sky130_fd_pr__nfet_01v8 / pfet_01v8, tt"},
    "gf180": {"vdd": 3.3, "lmin": 0.28, "uw_min": 0.36, "ibias": 20e-6, "model_note": "nfet_03v3 / pfet_03v3, typical"},
    "ihp130": {"vdd": 1.2, "lmin": 0.13, "uw_min": 0.30, "ibias": 20e-6, "model_note": "sg13_lv_nmos / pmos, mos_tt (PSP103 via OSDI)"},
}


@dataclass
class CaseSpec:
    case_id: str
    circuit_id: str
    pdk: str
    size: str                    # size-point tag, e.g. sW1_sL1 (or 'nominal')
    sizing: dict                 # device -> {w,l,nf} or {r}/{c}
    supply: dict                 # {"VDD": v, "VSS": 0}
    bias: dict                   # port -> value (V for VBx, A for IBx/IINx/IREFx)
    load: dict                   # testbench loads
    specs: dict                  # metric -> {"min":..,"max":..,"unit":..}
    notes: list = field(default_factory=list)

    def sha(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()


def scale_sizing(sizing, wscale=1.0, lscale=1.0, nf_fn=None):
    out = copy.deepcopy(sizing)
    for k, v in out.items():
        if "w" in v and "l" in v:
            v["w"] = round(v["w"] * wscale, 3); v["l"] = round(v["l"] * lscale, 3)
            if nf_fn: v["nf"] = nf_fn(k, v)
    return out
