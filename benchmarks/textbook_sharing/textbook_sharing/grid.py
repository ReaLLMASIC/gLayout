"""Size grid and size-derivation rule (fixed before any layout was built).

Grid: total-width multiplier sW in {0.5, 1.0, 1.5, 2.0} x gate-length multiplier sL in {1.0, 1.5, 2.0}
-> 12 size points per (topology, PDK); 18 x 3 x 12 = 648 requested cases.

Nominal point (sW = sL = 1) = the nominal design point of the topology and PDK (data/nominal/<topology>/<pdk>.json);
the changes in overrides.py are applied on top and recorded in every case.

Derivation rule (identical for every device of a case, so every width ratio inside the circuit is preserved exactly):
  L'  = L0 * sL, snapped to the 5 nm grid;
  W'  = W0 * sW for every MOS device;
  nf' = nf0 * sW when that is an integer for ALL MOS devices of the case (unit finger width unchanged);
        otherwise nf' = nf0 and the unit finger width becomes uw0 * sW for all devices;
  the request is REJECTED (parameter-illegal) when the resulting unit finger width is below the PDK minimum
  (contactable / model-valid width, PDK_POINT[pdk]['uw_min']) or is not on the 5 nm grid.
nf is therefore derived, never an independent sweep axis.  Passive R/C values, supply, bias currents and loads are
part of the circuit definition and are not scaled.  Two requests whose derived target netlists are identical
(same signature) are counted once (duplicates)."""
from __future__ import annotations
import copy, hashlib, json

SW = (0.5, 1.0, 1.5, 2.0)
SL = (1.0, 1.5, 2.0)
GRID = [(sw, sl) for sw in SW for sl in SL]
SELECTION_SIZES = [(1.0, 1.0), (2.0, 1.0), (1.0, 2.0), (2.0, 2.0)]
LLM_SIZES = [(2.0, 1.0), (2.0, 2.0)]
INTERFACE_SIZES = [(2.0, 1.0)]
SELECTION_TOPOLOGIES = ["C02", "C08", "C09", "C11", "C16", "C18"]
UW_MIN = {"sky130": 0.29, "gf180": 0.36, "ihp130": 0.30}     # = cases.PDK_POINT[pdk]['uw_min']
GRID_NM = 5


def size_tag(sw, sl):
    return f"sW{sw:g}_sL{sl:g}"


def _on_grid(x):
    return abs(round(x * 1000 / GRID_NM) * GRID_NM - x * 1000) < 1e-6


def snap5(x):
    return round(round(x * 1000 / GRID_NM) * GRID_NM / 1000, 4)


def derive_sizing(sizing0: dict, pdk: str, sw: float, sl: float):
    """Returns (sizing, derivation_record) or (None, rejection_record)."""
    mos = {k: v for k, v in sizing0.items() if "nf" in v}
    rec = {"sW": sw, "sL": sl, "rule": "grid.derive_sizing v1"}
    nf_scaled = {k: v["nf"] * sw for k, v in mos.items()}
    integer_nf = all(abs(x - round(x)) < 1e-9 and round(x) >= 1 for x in nf_scaled.values())
    out = copy.deepcopy(sizing0); per = {}
    for k, v in mos.items():
        uw0 = v["w"] / v["nf"]
        if integer_nf:
            nf = int(round(nf_scaled[k])); uw = uw0
        else:
            nf = v["nf"]; uw = uw0 * sw
        l = snap5(v["l"] * sl)
        if uw + 1e-9 < UW_MIN[pdk]:
            return None, {**rec, "status": "parameter_illegal", "reason": f"unit finger width {uw:.4g} um of {k} below the {pdk} minimum {UW_MIN[pdk]} um"}
        if not _on_grid(uw):
            return None, {**rec, "status": "parameter_illegal", "reason": f"unit finger width {uw:.6g} um of {k} not on the 5 nm grid"}
        w = round(uw * nf, 4)
        out[k] = {**v, "w": w, "l": l, "nf": nf}
        per[k] = {"w0": v["w"], "l0": v["l"], "nf0": v["nf"], "uw0": round(uw0, 4), "w": w, "l": l, "nf": nf, "uw": round(uw, 4),
                  "w_ratio": round(w / v["w"], 6), "l_ratio_exact": round(l / v["l"], 6)}
    rec.update({"status": "derived", "finger_rule": "nf scaled (unit width kept)" if integer_nf else "unit width scaled (nf kept)", "devices": per})
    return out, rec


def signature(circuit, pdk, sizing):
    """Identity of a derived target netlist: topology + PDK + every device's model-relevant size."""
    devs = []
    for d in circuit.devices:
        s = sizing[d.name]
        devs.append([d.name, d.kind, list(d.nets), {k: s.get(k) for k in ("w", "l", "nf", "r", "c") if k in s}])
    return hashlib.sha256(json.dumps([circuit.circuit_id, pdk, devs], sort_keys=True).encode()).hexdigest()[:16]
