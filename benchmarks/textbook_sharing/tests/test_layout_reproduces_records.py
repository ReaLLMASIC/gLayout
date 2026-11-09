"""Rebuilding two recorded OTA layouts (SKY130, nominal size) reproduces their recorded bounding-box areas exactly:
the unshared plan (256.0048 um^2) and the best verified plan of its catalogue (196.0921 um^2)."""
from textbook_sharing import paths
from textbook_sharing.run_case import load_case_dir
from textbook_sharing.circuits import CIRCUITS
from textbook_sharing.layout import build, device_specs, sharing_groups
from textbook_sharing.llm.plan_parser import parse_program, to_sharing_plan
from textbook_sharing.pdk import pdk_obj
from test_plan_parser import PROGRAM


def test_unshared_and_best_plan_areas():
    case, _ = load_case_dir(paths.CASES / "C08" / "sky130" / "sW1_sL1"); circ = CIRCUITS["C08"]; pdk = pdk_obj("sky130")
    ref = build(pdk, circ, case.sizing, mode="independent", name="test_ota_unshared")
    assert round(ref["assembly_stats"]["area_um2"], 4) == 256.0048
    groups = sharing_groups(device_specs(circ, case.sizing)); calls = parse_program(PROGRAM)
    plans = {str(i): to_sharing_plan(calls[i], g, pdk).to_json() for i, g in enumerate(groups)}
    best = build(pdk, circ, case.sizing, name="test_ota_best", plans=plans)
    assert round(best["assembly_stats"]["area_um2"], 4) == 196.0921
    chans = {}
    for tr in ref["trunks"]: chans.setdefault(tr["channel"], set()).add(tr["net"])
    assert chans.get(2) == {"net22"}                                       # unshared: a top channel only for net22
    assert 2 not in {tr["channel"] for tr in best["trunks"]}               # best plan: no top channel
