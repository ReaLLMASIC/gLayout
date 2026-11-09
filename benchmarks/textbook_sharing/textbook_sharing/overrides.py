"""Changes to the nominal design points, each with its reason, and the explicit list of test
auxiliaries of every case (they live in the testbench, never in the DUT layout, and never count towards core area).
Edited only before qualification; every change is recorded in the case notes."""
from __future__ import annotations
import copy

# sizing / bias / load changes applied to the nominal point before the grid derivation: cid -> pdk -> dict
CHANGES = {
    # class-AB output stage: the test returns RL/CL to mid-supply (see testbench.tb_buffer_ab)
    "C18": {"*": {"load": {"RL": 20e3, "CL": 5e-12, "vout_amp": 0.1}, "note": "RL/CL returned to an ideal mid-supply source; open-loop output-swing metric added"}},
}


def apply(cid, pdk, sizing, bias, load):
    s, b, l = copy.deepcopy(sizing), copy.deepcopy(bias), copy.deepcopy(load); notes = []
    for key in ("*", pdk):
        ch = CHANGES.get(cid, {}).get(key)
        if not ch: continue
        for dev, v in ch.get("sizing", {}).items(): s[dev] = {**s.get(dev, {}), **v}
        b.update(ch.get("bias", {})); l.update(ch.get("load", {}))
        if ch.get("note"): notes.append(ch["note"])
    return s, b, l, notes


def test_auxiliaries(cid, case):
    """Everything the testbench adds around the DUT (disclosed; not part of the core layout or its area)."""
    aux = []
    for port, v in case.bias.items():
        if isinstance(v, dict) and "replica" in v:
            aux.append({"kind": "replica_bias", "port": port, "replica_of": v["replica"], "current_A": v["current"], "variant": v.get("kind", "diode")})
        elif isinstance(v, dict) and "expr" in v:
            aux.append({"kind": "behavioural_bias", "port": port, "expr": v["expr"]})
        elif isinstance(v, dict) and "i" in v:
            aux.append({"kind": "ideal_current_source", "port": port, "current_A": v["i"], "from": v.get("from", "VDD")})
        elif port == "IREF":
            aux.append({"kind": "reference_current_value", "value_A": v})
    cat_aux = {
        "single": ["DC servo (1 MH / 1 MF) setting V_in,dc = V_out,dc", "load capacitor"],
        "ota": ["bounded tanh DC servo setting V_out,dc", "ideal input common-mode source", "load capacitor"],
        "twostage": ["bounded tanh DC servo setting V_out,dc", "ideal input common-mode source", "load capacitor"],
        "ota_fd": ["ideal common-mode feedback on VB4", "ideal input common-mode source", "load capacitors"],
        "diff_cs": ["ideal common-mode feedback on VB1", "ideal input common-mode source", "load capacitors"],
        "diff_r": ["ideal input common-mode source", "load capacitors"],
        "follower": ["ideal input source", "load resistor and capacitor"],
        "buffer_ab": ["bounded tanh DC servo (freezable)", "mid-supply load return", "load resistor and capacitor"],
        "mirror": ["ideal reference current source(s)", "ideal output voltage source (swept)"],
    }
    from textbook_sharing.testbench import CATEGORY
    aux += [{"kind": "testbench_element", "what": w} for w in cat_aux[CATEGORY[cid]]]
    return aux
